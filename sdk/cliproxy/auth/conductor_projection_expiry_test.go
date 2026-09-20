package auth

import (
	"testing"
	"time"
)

func TestModelProjectionUsesSchedulerRecoveryDeadline(t *testing.T) {
	now := time.Date(2026, 9, 20, 12, 0, 0, 0, time.UTC)
	for _, name := range []string{"active-transient", "expired-transient", "undated-failure", "disabled-model", "disabled-auth", "auth-cooldown", "expired-auth-cooldown", "quota"} {
		t.Run(name, func(t *testing.T) {
			state := &ModelState{Unavailable: true, NextRetryAfter: now.Add(time.Minute), Status: StatusError}
			auth := &Auth{ID: "test-auth", Provider: "codex", ModelStates: map[string]*ModelState{"model": state}}
			wantBlocked := true
			wantDeadline := now.Add(time.Minute)
			switch name {
			case "expired-transient":
				state.NextRetryAfter = now.Add(-time.Minute)
				wantBlocked, wantDeadline = false, time.Time{}
			case "undated-failure":
				state.NextRetryAfter = time.Time{}
				wantDeadline = time.Time{}
			case "disabled-model":
				state.Status = StatusDisabled
				wantDeadline = time.Time{}
			case "disabled-auth":
				auth.Disabled = true
				wantDeadline = time.Time{}
			case "auth-cooldown", "expired-auth-cooldown":
				auth.ModelStates = nil
				auth.Unavailable = true
				auth.NextRetryAfter = now.Add(time.Minute)
				if name == "expired-auth-cooldown" {
					auth.NextRetryAfter = now.Add(-time.Minute)
					wantBlocked, wantDeadline = false, time.Time{}
				}
			case "quota":
				state.Quota = QuotaState{Exceeded: true, Reason: "quota", NextRecoverAt: now.Add(2 * time.Minute)}
				wantDeadline = state.Quota.NextRecoverAt
			}
			manager := NewManager(nil, nil, nil)
			projection := manager.clientModelProjectionForAuth(auth, "model", now)
			blocked, _, deadline := isAuthBlockedForModel(auth, "model", now)
			if blocked != wantBlocked || !deadline.Equal(wantDeadline) || projection.Suspended != blocked || !projection.SuspendUntil.Equal(deadline) {
				t.Fatalf("projection=%+v scheduler blocked=%v deadline=%v; want blocked=%v deadline=%v", projection, blocked, deadline, wantBlocked, wantDeadline)
			}
			if name == "quota" && (!projection.QuotaExceeded || projection.SuspendReason != "quota") {
				t.Fatalf("quota projection changed: %+v", projection)
			}
		})
	}
}
