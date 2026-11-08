package auth

import (
	"encoding/json"
	"testing"
)

func TestAntigravityTokenLimitsSurviveDiscoveryPersistenceAndClone(t *testing.T) {
	hints, ok := ParseAntigravityModelCapabilityHints([]byte(`{"models":{" model-a ":{"maxTokens":250000,"maxOutputTokens":64000},"model-b":{"maxTokens":-1},"model-c":{"maxOutputTokens":8192}}}`))
	if !ok || len(hints.ModelLimits) != 2 || hints.ModelLimits["model-a"].ContextLength != 250000 || hints.ModelLimits["model-c"].MaxCompletionTokens != 8192 {
		t.Fatalf("discovery lost declared limits: %+v", hints)
	}
	cloned := hints.Clone()
	cloned.ModelLimits["model-a"] = AntigravityModelLimits{ContextLength: 1}
	if hints.ModelLimits["model-a"].ContextLength != 250000 {
		t.Fatal("clone shares limits")
	}
	value := BuildPersistedAntigravityCapabilityHints("project", "https://example.com", hints)
	encoded, err := json.Marshal(map[string]any{AntigravityPersistedHintsMetaKey: value})
	if err != nil {
		t.Fatal(err)
	}
	var metadata map[string]any
	if err := json.Unmarshal(encoded, &metadata); err != nil {
		t.Fatal(err)
	}
	persisted, ok := ParsePersistedAntigravityCapabilityHints(metadata, "project", "https://example.com")
	if !ok || len(persisted.ModelLimits) != 2 || persisted.ModelLimits["model-a"] != hints.ModelLimits["model-a"] || persisted.ModelLimits["model-c"] != hints.ModelLimits["model-c"] {
		t.Fatalf("persistent cache lost limits: %+v", persisted)
	}
}
