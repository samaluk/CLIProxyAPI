package cliproxy

import (
	"context"
	"encoding/json"
	"reflect"
	"testing"

	codexmodels "github.com/router-for-me/CLIProxyAPI/v7/internal/client/codex/models"
	"github.com/router-for-me/CLIProxyAPI/v7/internal/config"
	"github.com/router-for-me/CLIProxyAPI/v7/internal/registry"
	coreauth "github.com/router-for-me/CLIProxyAPI/v7/sdk/cliproxy/auth"
)

func TestConfiguredCodexMetadataReachesPrefixedCatalog(t *testing.T) {
	const authID = "configured-codex-metadata-test"
	const route = "work/litellm/pro"
	efforts := []string{"none", "low", "medium", "high", "xhigh", "max"}
	entry := config.CodexKey{
		APIKey: "synthetic-key", Prefix: "work", BaseURL: "https://gateway.example.com",
		Models: []config.CodexModel{{
			Name: "deployment-pro", Alias: "litellm/pro", CanonicalModelID: " gpt-5.6-luna ",
			MaxContextLength: 1050000, MaxCompletionTokens: 128000,
			InputModalities: []string{"TEXT", " image ", "image"}, OutputModalities: []string{"text"},
			Thinking: &registry.ThinkingSupport{Levels: efforts, ZeroAllowed: true},
		}},
	}
	service := &Service{cfg: &config.Config{CodexKey: []config.CodexKey{entry}}}
	r := registry.GetGlobalRegistry()
	t.Cleanup(func() { r.UnregisterClient(authID) })
	service.registerModelsForAuth(context.Background(), &coreauth.Auth{
		ID: authID, Provider: "codex", Prefix: "work", Status: coreauth.StatusActive,
		Attributes: map[string]string{coreauth.AttributeAPIKey: entry.APIKey, coreauth.AttributeConfigIndex: "0", coreauth.AttributeSource: "config:codex:test", "base_url": entry.BaseURL},
	})
	info := registry.LookupModelInfo(route, "codex")
	if info == nil || info.MetadataModelID != "gpt-5.6-luna" || info.MaxCompletionTokens != 128000 || !info.ExplicitInputModalities {
		t.Fatalf("prefixed registration lost metadata: %+v", info)
	}
	response := codexmodels.BuildResponseForClient(r.GetAvailableModels("openai"), r.GetModelProviders, false, "cpa")
	// Decode the actual response shape used by clients instead of relying on Go slice types.
	encoded, errJSON := json.Marshal(response)
	if errJSON != nil {
		t.Fatal(errJSON)
	}
	var catalog struct {
		Models []struct {
			Slug        string   `json:"slug"`
			CanonicalID string   `json:"canonical_model_id"`
			Context     int      `json:"context_window"`
			MaxContext  int      `json:"max_context_window"`
			MaxTokens   int      `json:"max_tokens"`
			Inputs      []string `json:"supported_input_modalities"`
			CodexInputs []string `json:"input_modalities"`
			Outputs     []string `json:"output_modalities"`
			Efforts     []struct {
				Effort string `json:"effort"`
			} `json:"supported_reasoning_levels"`
		} `json:"models"`
	}
	if errJSON = json.Unmarshal(encoded, &catalog); errJSON != nil {
		t.Fatal(errJSON)
	}
	for _, model := range catalog.Models {
		if model.Slug != route {
			continue
		}
		if model.CanonicalID != "gpt-5.6-luna" || model.Context != 1050000 || model.MaxContext != 1050000 || model.MaxTokens != 128000 {
			t.Fatalf("catalog identity/limits mismatch: %+v", model)
		}
		if !reflect.DeepEqual(model.Inputs, []string{"text", "image"}) || !reflect.DeepEqual(model.CodexInputs, []string{"text", "image"}) || !reflect.DeepEqual(model.Outputs, []string{"text"}) {
			t.Fatalf("catalog modalities mismatch: %+v", model)
		}
		gotEfforts := make([]string, len(model.Efforts))
		for i, effort := range model.Efforts {
			gotEfforts[i] = effort.Effort
		}
		if !reflect.DeepEqual(gotEfforts, efforts) {
			t.Fatalf("efforts = %v, want %v", gotEfforts, efforts)
		}
		return
	}
	t.Fatal("catalog omitted configured route")
}

func TestConfiguredCodexMetadataAbsentRemainsUnknown(t *testing.T) {
	for _, model := range []config.CodexModel{
		{Name: "deployment-pro", Alias: "litellm/pro"},
		{Name: "deployment-pro", Alias: "litellm/pro", CanonicalModelID: " ", MaxCompletionTokens: -1, InputModalities: []string{" "}, OutputModalities: []string{}},
	} {
		info := buildCodexConfigModels(&config.CodexKey{Models: []config.CodexModel{model}})[0]
		if info.MetadataModelID != "deployment-pro" || info.MaxCompletionTokens != 0 || info.SupportedInputModalities != nil || info.SupportedOutputModalities != nil || info.ExplicitInputModalities {
			t.Fatalf("absent metadata was inferred: %+v", info)
		}
	}
}
