package auth

import (
	"testing"

	"github.com/router-for-me/CLIProxyAPI/v7/internal/config"
)

func TestCanonicalMetadataDoesNotChangeUpstreamRoute(t *testing.T) {
	cfg := &config.Config{CodexKey: []config.CodexKey{{
		APIKey: "synthetic-key", BaseURL: "https://gateway.example.com", Prefix: "work",
		Models: []config.CodexModel{{Name: "deployment-pro", Alias: "litellm/pro", CanonicalModelID: "gpt-5.6-luna", MaxCompletionTokens: 128000}},
	}}}
	auth := &Auth{ID: "canonical-routing", Provider: "codex", Prefix: "work", Attributes: map[string]string{
		AttributeAPIKey: "synthetic-key", AttributeConfigIndex: "0", "base_url": "https://gateway.example.com",
	}}
	manager := NewManager(nil, nil, nil)
	manager.SetConfig(cfg)
	for _, requested := range []string{"litellm/pro", "work/litellm/pro"} {
		result := manager.resolveExecutionAliasResult(auth, requested)
		if result.UpstreamModel != "deployment-pro" {
			t.Fatalf("route %q resolves to %q, want deployment-pro", requested, result.UpstreamModel)
		}
	}
}
