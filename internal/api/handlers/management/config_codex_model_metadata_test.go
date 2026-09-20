package management

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/router-for-me/CLIProxyAPI/v7/internal/config"
)

func TestPatchCodexModelMetadataPersistsAndClears(t *testing.T) {
	h := &Handler{
		cfg: &config.Config{CodexKey: []config.CodexKey{{
			APIKey: "synthetic-key", BaseURL: "https://gateway.example.com", Prefix: "work",
		}}},
		configFilePath: writeTestConfigFile(t),
	}
	for _, tc := range []struct {
		name, body string
		want       config.CodexModel
	}{
		{
			name: "declared metadata",
			body: `{"name":"deployment-pro","alias":"litellm/pro","canonical-model-id":"gpt-5.6-luna","max-context-length":1050000,"max-completion-tokens":128000,"input-modalities":["text","image"],"output-modalities":["text"]}`,
			want: config.CodexModel{Name: "deployment-pro", Alias: "litellm/pro", CanonicalModelID: "gpt-5.6-luna", MaxContextLength: 1050000, MaxCompletionTokens: 128000, InputModalities: []string{"text", "image"}, OutputModalities: []string{"text"}},
		},
		{
			name: "replacement removes metadata",
			body: `{"name":"deployment-pro","alias":"litellm/pro"}`,
			want: config.CodexModel{Name: "deployment-pro", Alias: "litellm/pro"},
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			rec := httptest.NewRecorder()
			ctx, _ := gin.CreateTestContext(rec)
			ctx.Request = httptest.NewRequest(http.MethodPatch, "/v0/management/codex-api-key", strings.NewReader(`{"index":0,"value":{"models":[`+tc.body+`]}}`))
			ctx.Request.Header.Set("Content-Type", "application/json")
			h.PatchCodexKey(ctx)
			if rec.Code != http.StatusOK {
				t.Fatalf("PATCH status = %d: %s", rec.Code, rec.Body.String())
			}

			loaded, errLoad := config.LoadConfig(h.configFilePath)
			if errLoad != nil {
				t.Fatal(errLoad)
			}
			if len(loaded.CodexKey) != 1 || len(loaded.CodexKey[0].Models) != 1 || !reflect.DeepEqual(loaded.CodexKey[0].Models[0], tc.want) {
				t.Fatalf("metadata did not survive YAML persistence/reload: %+v", loaded.CodexKey)
			}
			if loaded.CodexKey[0].Prefix != "work" || loaded.CodexKey[0].APIKey != "synthetic-key" {
				t.Fatal("model metadata update changed credential identity")
			}
			h.cfg = loaded
			rec = httptest.NewRecorder()
			ctx, _ = gin.CreateTestContext(rec)
			h.GetCodexKeys(ctx)
			var got struct {
				Keys []config.CodexKey `json:"codex-api-key"`
			}
			if errJSON := json.Unmarshal(rec.Body.Bytes(), &got); errJSON != nil {
				t.Fatal(errJSON)
			}
			if len(got.Keys) != 1 || len(got.Keys[0].Models) != 1 || !reflect.DeepEqual(got.Keys[0].Models[0], tc.want) {
				t.Fatalf("GET metadata changed: %s", rec.Body.String())
			}
		})
	}
}
