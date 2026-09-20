package pluginhost

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/router-for-me/CLIProxyAPI/v7/internal/clienterror"
	"github.com/router-for-me/CLIProxyAPI/v7/internal/interfaces"
	"github.com/router-for-me/CLIProxyAPI/v7/internal/registry"
	"github.com/router-for-me/CLIProxyAPI/v7/sdk/api/handlers"
	coreauth "github.com/router-for-me/CLIProxyAPI/v7/sdk/cliproxy/auth"
	coreexecutor "github.com/router-for-me/CLIProxyAPI/v7/sdk/cliproxy/executor"
	"github.com/router-for-me/CLIProxyAPI/v7/sdk/pluginabi"
	"github.com/router-for-me/CLIProxyAPI/v7/sdk/pluginapi"
)

type policyWireScheduler struct {
	calls int
	deny  bool
}

func (s *policyWireScheduler) PickAuth(ctx context.Context, req pluginapi.SchedulerPickRequest) (pluginapi.SchedulerPickResponse, bool, error) {
	s.calls++
	if !s.deny {
		return pluginapi.SchedulerPickResponse{Handled: true, AuthID: req.Candidates[0].ID}, true, nil
	}
	// Use the actual plugin JSON decoder, including the explicit false field.
	client := staticEnvelopePluginClient{raw: []byte(`{"ok":false,"error":{"code":"scope_denied","message":"downstream key scope mismatch","http_status":403,"retryable":false}}`)}
	result, errCall := callPlugin[pluginapi.SchedulerPickResponse](ctx, client, pluginabi.MethodSchedulerPick, req)
	return result, true, errCall
}

type policyWireExecutor struct {
	ids []string
}

func (*policyWireExecutor) Identifier() string { return "policy-wire-test" }
func (e *policyWireExecutor) Execute(_ context.Context, auth *coreauth.Auth, _ coreexecutor.Request, _ coreexecutor.Options) (coreexecutor.Response, error) {
	e.ids = append(e.ids, auth.ID)
	if auth.ID == "policy-wire-a" {
		return coreexecutor.Response{}, &pluginabi.Error{Code: "scope_denied", Message: "upstream credential refused", HTTPStatus: http.StatusForbidden}
	}
	return coreexecutor.Response{Payload: []byte(`{"ok":true}`)}, nil
}
func (e *policyWireExecutor) ExecuteStream(ctx context.Context, auth *coreauth.Auth, req coreexecutor.Request, opts coreexecutor.Options) (*coreexecutor.StreamResult, error) {
	if _, errExecute := e.Execute(ctx, auth, req, opts); errExecute != nil {
		return nil, errExecute
	}
	chunks := make(chan coreexecutor.StreamChunk)
	close(chunks)
	return &coreexecutor.StreamResult{Chunks: chunks}, nil
}
func (e *policyWireExecutor) CountTokens(ctx context.Context, auth *coreauth.Auth, req coreexecutor.Request, opts coreexecutor.Options) (coreexecutor.Response, error) {
	return e.Execute(ctx, auth, req, opts)
}
func (*policyWireExecutor) Refresh(_ context.Context, auth *coreauth.Auth) (*coreauth.Auth, error) {
	return auth, nil
}
func (*policyWireExecutor) HttpRequest(context.Context, *coreauth.Auth, *http.Request) (*http.Response, error) {
	return nil, nil
}

func TestSchedulerPolicyWireErrorStopsRetriesAndPreservesClientContract(t *testing.T) {
	for _, kind := range []string{"non-stream", "stream", "count"} {
		for _, deny := range []bool{true, false} {
			name := kind + "/executor-failover"
			if deny {
				name = kind + "/scheduler-denial"
			}
			t.Run(name, func(t *testing.T) {
				manager := coreauth.NewManager(nil, &coreauth.FillFirstSelector{}, nil)
				manager.SetRetryConfig(3, 0, 0)
				executor := &policyWireExecutor{}
				manager.RegisterExecutor(executor)
				scheduler := &policyWireScheduler{deny: deny}
				manager.SetPluginScheduler(scheduler)
				for _, id := range []string{"policy-wire-a", "policy-wire-b"} {
					registry.GetGlobalRegistry().RegisterClient(id, executor.Identifier(), []*registry.ModelInfo{{ID: "policy-wire-model"}})
					t.Cleanup(func() { registry.GetGlobalRegistry().UnregisterClient(id) })
					if _, errRegister := manager.Register(context.Background(), &coreauth.Auth{ID: id, Provider: executor.Identifier(), Metadata: map[string]any{"disable_cooling": true, "request_retry": 3}}); errRegister != nil {
						t.Fatal(errRegister)
					}
				}
				req := coreexecutor.Request{Model: "policy-wire-model"}
				var errExecute error
				switch kind {
				case "stream":
					_, errExecute = manager.ExecuteStream(context.Background(), []string{executor.Identifier()}, req, coreexecutor.Options{Stream: true})
				case "count":
					_, errExecute = manager.ExecuteCount(context.Background(), []string{executor.Identifier()}, req, coreexecutor.Options{})
				default:
					_, errExecute = manager.Execute(context.Background(), []string{executor.Identifier()}, req, coreexecutor.Options{})
				}
				if !deny {
					if errExecute != nil || len(executor.ids) != 2 || executor.ids[0] != "policy-wire-a" || executor.ids[1] != "policy-wire-b" {
						t.Fatalf("executor 403 must retain credential failover: ids=%v error=%v", executor.ids, errExecute)
					}
					return
				}
				if scheduler.calls != 1 || len(executor.ids) != 0 {
					t.Fatalf("policy denial retried or executed: scheduler calls=%d, executor ids=%v", scheduler.calls, executor.ids)
				}
				status := clienterror.HTTPStatusFromError(errExecute)
				if status != http.StatusForbidden {
					t.Fatalf("status = %d, want 403; error=%v", status, errExecute)
				}
				recorder := httptest.NewRecorder()
				ctx, _ := gin.CreateTestContext(recorder)
				handlers.NewBaseAPIHandlers(nil, nil).WriteErrorResponse(ctx, &interfaces.ErrorMessage{StatusCode: status, Error: errExecute})
				var response struct {
					Error struct {
						Message   string `json:"message"`
						Type      string `json:"type"`
						Code      string `json:"code"`
						Retryable *bool  `json:"retryable"`
					} `json:"error"`
				}
				if errDecode := json.Unmarshal(recorder.Body.Bytes(), &response); errDecode != nil {
					t.Fatal(errDecode)
				}
				if recorder.Code != http.StatusForbidden || response.Error.Code != "scope_denied" || response.Error.Type != "permission_error" || response.Error.Retryable == nil || *response.Error.Retryable || response.Error.Message != "downstream key scope mismatch" {
					t.Fatalf("policy HTTP response = %d %s", recorder.Code, recorder.Body.String())
				}
			})
		}
	}
}
