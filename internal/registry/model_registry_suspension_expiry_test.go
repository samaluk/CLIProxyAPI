package registry

import (
	"testing"
	"time"
)

func TestFiniteSuspensionExpiresInCachedCatalogWithoutAnotherProjection(t *testing.T) {
	r := newTestModelRegistry()
	r.RegisterClient("cooldown-client", "codex", []*ModelInfo{{ID: "cooldown-model"}})
	now := time.Now()
	deadline := now.Add(time.Minute)
	projection := ClientModelProjection{ModelID: "cooldown-model", Suspended: true, SuspendReason: "transient_error", SuspendUntil: deadline}
	if !r.ApplyClientModelProjections("cooldown-client", r.ClientRegistrationEpoch("cooldown-client"), 1, []ClientModelProjection{projection}) {
		t.Fatal("projection rejected")
	}
	if got := r.getAvailableModelsAt("openai", now); len(got) != 0 {
		t.Fatalf("model visible before cooldown expires: %v", got)
	}
	if expiresAt := r.availableModelsCache["openai"].expiresAt; !expiresAt.Equal(deadline) {
		t.Fatalf("cache expires at %v, want %v", expiresAt, deadline)
	}
	// Advancing the query clock must be sufficient. No successful request,
	// re-registration, auth refresh, or manual resume is needed.
	if got := r.getAvailableModelsAt("openai", deadline); len(got) != 1 || got[0]["id"] != "cooldown-model" {
		t.Fatalf("model did not reappear at recovery: %v", got)
	}
}

func TestExpiredSuspensionAgreesAcrossRegistryQueries(t *testing.T) {
	r := newTestModelRegistry()
	r.RegisterClient("cooldown-client", "codex", []*ModelInfo{{ID: "cooldown-model"}})
	projection := ClientModelProjection{ModelID: "cooldown-model", Suspended: true, SuspendReason: "transient_error", SuspendUntil: time.Now().Add(-time.Minute)}
	r.ApplyClientModelProjections("cooldown-client", r.ClientRegistrationEpoch("cooldown-client"), 1, []ClientModelProjection{projection})
	if r.IsModelSuspendedForClient("cooldown-client", "cooldown-model") || r.GetModelCount("cooldown-model") != 1 || len(r.GetAvailableModelInfos()) != 1 || len(r.GetAvailableModelsByProvider("codex")) != 1 || len(r.GetAvailableModels("openai")) != 1 {
		t.Fatal("expired suspension is still visible to a registry query")
	}
}

func TestSuspensionDeadlineChangesInvalidateCacheAndManualSuspensionStays(t *testing.T) {
	r := newTestModelRegistry()
	r.RegisterClient("cooldown-client", "codex", []*ModelInfo{{ID: "cooldown-model"}})
	now := time.Now()
	projection := ClientModelProjection{ModelID: "cooldown-model", Suspended: true, SuspendReason: "transient_error", SuspendUntil: now.Add(time.Minute)}
	epoch := r.ClientRegistrationEpoch("cooldown-client")
	r.ApplyClientModelProjections("cooldown-client", epoch, 1, []ClientModelProjection{projection})
	r.getAvailableModelsAt("openai", now)
	projection.SuspendUntil = now.Add(2 * time.Minute)
	r.ApplyClientModelProjections("cooldown-client", epoch, 2, []ClientModelProjection{projection})
	if got := r.getAvailableModelsAt("openai", now.Add(time.Minute)); len(got) != 0 {
		t.Fatal("shorter stale deadline made the model available")
	}
	if !r.availableModelsCache["openai"].expiresAt.Equal(projection.SuspendUntil) {
		t.Fatal("extended deadline did not replace cached expiry")
	}
	r.SuspendClientModel("cooldown-client", "cooldown-model", "manual")
	if got := r.getAvailableModelsAt("openai", now.Add(time.Hour)); len(got) != 0 {
		t.Fatal("manual suspension inherited a finite cooldown deadline")
	}
	r.ResumeClientModel("cooldown-client", "cooldown-model")
	if len(r.GetAvailableModels("openai")) != 1 || len(r.models["cooldown-model"].SuspensionDeadlines) != 0 {
		t.Fatal("manual resume retained a suspension deadline")
	}
}

func TestUndatedAndQuotaSuspensionsKeepExistingCatalogBehavior(t *testing.T) {
	for _, reason := range []string{"disabled", "manual", "quota"} {
		t.Run(reason, func(t *testing.T) {
			r := newTestModelRegistry()
			r.RegisterClient("client", "codex", []*ModelInfo{{ID: "model"}})
			r.ApplyClientModelProjections("client", r.ClientRegistrationEpoch("client"), 1, []ClientModelProjection{{ModelID: "model", Suspended: true, SuspendReason: reason}})
			got := r.getAvailableModelsAt("openai", time.Now().Add(24*time.Hour))
			if (len(got) == 1) != (reason == "quota") {
				t.Fatalf("existing %s visibility changed: %v", reason, got)
			}
		})
	}
}

func TestReregisterClearsPreviousSuspensionDeadline(t *testing.T) {
	r := newTestModelRegistry()
	models := []*ModelInfo{{ID: "model"}}
	r.RegisterClient("client", "codex", models)
	r.ApplyClientModelProjections("client", r.ClientRegistrationEpoch("client"), 1, []ClientModelProjection{{ModelID: "model", Suspended: true, SuspendReason: "transient_error", SuspendUntil: time.Now().Add(time.Minute)}})
	r.RegisterClient("client", "codex", models)
	if len(r.models["model"].SuspensionDeadlines) != 0 || len(r.GetAvailableModels("openai")) != 1 {
		t.Fatal("re-registration retained an old suspension")
	}
}
