package auth

import (
	"context"
	"errors"
	"net/http"
	"strings"
	"testing"
	"time"

	internalconfig "github.com/router-for-me/CLIProxyAPI/v7/internal/config"
	"github.com/router-for-me/CLIProxyAPI/v7/internal/registry"
	cliproxyexecutor "github.com/router-for-me/CLIProxyAPI/v7/sdk/cliproxy/executor"
)

func TestManagerPrefixedAPIKeyAliasPreservesCooldownCause(t *testing.T) {
	for _, scheduler := range []string{"builtin", "plugin"} {
		for _, status := range []int{http.StatusServiceUnavailable, http.StatusTooManyRequests} {
			for _, path := range []string{"execute", "stream", "count"} {
				t.Run(scheduler+"/"+http.StatusText(status)+"/"+path, func(t *testing.T) {
					const route, alias, upstream = "work/gateway/model", "gateway/model", "upstream-model"
					manager := NewManager(nil, &RoundRobinSelector{}, nil)
					manager.SetConfig(&internalconfig.Config{CodexKey: []internalconfig.CodexKey{{APIKey: "synthetic-key", Prefix: "work", Models: []internalconfig.CodexModel{{Name: upstream, Alias: alias}}}}})
					manager.SetRetryConfig(0, 0, 0)
					manager.RegisterExecutor(&aliasRoutingExecutor{id: "codex"})
					if scheduler == "plugin" {
						manager.SetPluginScheduler(&fakePluginScheduler{})
					}
					a := &Auth{ID: "prefixed-alias-" + t.Name(), Provider: "codex", Prefix: "work", Status: StatusActive, Attributes: map[string]string{"api_key": "synthetic-key"}}
					if _, err := manager.Register(context.Background(), a); err != nil {
						t.Fatal(err)
					}
					reg := registry.GetGlobalRegistry()
					reg.RegisterClient(a.ID, "codex", []*registry.ModelInfo{{ID: route}})
					t.Cleanup(func() { reg.UnregisterClient(a.ID) })
					// Record the actual execution result key, as a failed preceding turn does.
					stateModel := manager.stateModelForExecution(a, route, upstream, false)
					retryAfter := time.Hour
					manager.MarkResult(context.Background(), Result{AuthID: a.ID, Provider: "codex", Model: stateModel, RouteModel: route, Error: &Error{HTTPStatus: status, Message: "synthetic upstream failure"}, RetryAfter: &retryAfter})
					var err error
					switch path {
					case "execute":
						_, err = manager.Execute(context.Background(), []string{"codex"}, cliproxyexecutor.Request{Model: route}, cliproxyexecutor.Options{})
					case "stream":
						_, err = manager.ExecuteStream(context.Background(), []string{"codex"}, cliproxyexecutor.Request{Model: route}, cliproxyexecutor.Options{Stream: true})
					case "count":
						_, err = manager.ExecuteCount(context.Background(), []string{"codex"}, cliproxyexecutor.Request{Model: route}, cliproxyexecutor.Options{})
					}
					if err == nil || !strings.Contains(err.Error(), "synthetic upstream failure") {
						t.Fatalf("request error = %v, want original cooldown cause", err)
					}
					var authErr *Error
					if errors.As(err, &authErr) && authErr.Code == "auth_not_found" {
						t.Fatalf("active cooldown was replaced by %v", err)
					}
					// The same route remains usable after its cooldown is cleared.
					manager.MarkResult(context.Background(), Result{AuthID: a.ID, Provider: "codex", Model: stateModel, RouteModel: route, Success: true})
					response, err := manager.Execute(context.Background(), []string{"codex"}, cliproxyexecutor.Request{Model: route}, cliproxyexecutor.Options{})
					if err != nil || string(response.Payload) != upstream {
						t.Fatalf("recovered execution = %s, %v; want original configured upstream", response.Payload, err)
					}
				})
			}
		}
	}
}

func TestManagerPrefixedAPIKeyPoolKeepsHealthyTargetAvailable(t *testing.T) {
	const alias, route = "gateway/pool", "work/gateway/pool"
	executor := &openAICompatPoolExecutor{id: openAICompatPoolProviderKey}
	manager := newOpenAICompatPoolTestManager(t, route, []internalconfig.OpenAICompatibilityModel{
		{Name: "unavailable-model", Alias: alias}, {Name: "healthy-model", Alias: alias},
	}, executor)
	a, _ := manager.GetByID("pool-auth-" + t.Name())
	a.Prefix = "work"
	if _, err := manager.Update(context.Background(), a); err != nil {
		t.Fatal(err)
	}
	retryAfter := time.Hour
	manager.MarkResult(context.Background(), Result{AuthID: a.ID, Provider: openAICompatPoolProviderKey, Model: "unavailable-model", RouteModel: route, Error: &Error{HTTPStatus: 429, Message: "synthetic target cooldown"}, RetryAfter: &retryAfter})
	for range 2 {
		response, err := manager.Execute(context.Background(), []string{openAICompatPoolProviderKey}, cliproxyexecutor.Request{Model: route}, cliproxyexecutor.Options{})
		if err != nil || string(response.Payload) != "healthy-model" {
			t.Fatalf("pool execution = %s, %v; want healthy target", response.Payload, err)
		}
	}
}

func TestManagerPrefixedAPIKeySingleCompatAliasPreservesCooldown(t *testing.T) {
	const alias, route = "gateway/alias", "work/gateway/alias"
	manager := newOpenAICompatPoolTestManager(t, route, []internalconfig.OpenAICompatibilityModel{{Name: "upstream-model", Alias: alias}}, nil)
	a, _ := manager.GetByID("pool-auth-" + t.Name())
	a.Prefix = "work"
	if _, err := manager.Update(context.Background(), a); err != nil {
		t.Fatal(err)
	}
	manager.MarkResult(context.Background(), Result{AuthID: a.ID, Provider: openAICompatPoolProviderKey, Model: route, RouteModel: route, Error: &Error{HTTPStatus: 503, Message: "synthetic compatibility cooldown"}})
	_, err := manager.Execute(context.Background(), []string{openAICompatPoolProviderKey}, cliproxyexecutor.Request{Model: route}, cliproxyexecutor.Options{})
	if err == nil || !strings.Contains(err.Error(), "synthetic compatibility cooldown") {
		t.Fatalf("request error = %v, want original cooldown cause", err)
	}
}
