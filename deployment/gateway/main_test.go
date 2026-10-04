package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func fixtureGateway(t *testing.T, handler http.HandlerFunc) *gateway {
	t.Helper()
	backend := httptest.NewServer(handler)
	t.Cleanup(backend.Close)
	g, err := newGateway(config{Listen: ":0", Backend: backend.URL, AuthDir: t.TempDir(), ClientVersion: "0.160.0", Profiles: []profile{{Scope: "work", Key: "fixture-work-key-12345"}, {Scope: "personal", Key: "fixture-personal-key-12345"}}})
	if err != nil {
		t.Fatal(err)
	}
	return g
}

func TestScopeAuthenticationAndConditionalRevision(t *testing.T) {
	contextWindow := 1000
	g := fixtureGateway(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer fixture-work-key-12345" {
			t.Error("wrong backend credential")
		}
		json.NewEncoder(w).Encode(map[string]any{"models": []model{{"slug": "work/litellm/m", "context_window": contextWindow, "base_instructions": "untrusted"}, {"slug": "personal/commandcode/m", "context_window": 10}}})
	})
	request := func(key, etag string) *httptest.ResponseRecorder {
		r := httptest.NewRequest("GET", "/catalog/v1", nil)
		r.Header.Set("Authorization", "Bearer "+key)
		r.Header.Set("If-None-Match", etag)
		w := httptest.NewRecorder()
		g.serveCatalog(w, r)
		return w
	}
	if w := request("unknown", ""); w.Code != 401 {
		t.Fatalf("unauthorized: %d", w.Code)
	}
	w := request("fixture-work-key-12345", "")
	if w.Code != 200 || strings.Contains(w.Body.String(), "personal/") || strings.Contains(w.Body.String(), "untrusted") {
		t.Fatalf("unsafe catalog %d", w.Code)
	}
	etag := w.Header().Get("ETag")
	if request("fixture-work-key-12345", etag).Code != 304 {
		t.Fatal("unchanged catalog should be conditional")
	}
	entry := g.cache["work"]
	entry.at = time.Time{}
	g.cache["work"] = entry
	contextWindow = 2000
	w = request("fixture-work-key-12345", etag)
	if w.Code != 200 || w.Header().Get("ETag") == etag {
		t.Fatal("provider change needs new revision")
	}
}

func TestAccountPrecedenceAndExplicitEmptyLists(t *testing.T) {
	base := model{"slug": "personal/codex-oauth/m", "max_tokens": float64(1), "default_reasoning_level": "high", "additional_speed_tiers": []any{"ultrafast"}, "supported_input_modalities": []any{"image"}}
	mergeCapabilities(base, model{"slug": "m", "max_output_tokens": float64(20), "input_modalities": []any{"text"}, "supported_reasoning_levels": []any{}, "service_tiers": []any{map[string]any{"id": "priority"}}, "base_instructions": "untrusted"})
	if base["max_tokens"] != float64(20) || base["default_reasoning_level"] != nil || base["base_instructions"] != nil {
		t.Fatal("account must override aliases without importing prompts")
	}
	data, _ := json.Marshal(base)
	if strings.Contains(string(data), "ultrafast") || strings.Contains(string(data), "image") {
		t.Fatal("stale aliases survived account restriction")
	}
	mergeCapabilities(base, model{"additional_speed_tiers": []any{"fast", "ultrafast"}})
	data, _ = json.Marshal(base)
	if !strings.Contains(string(data), "ultrafast") {
		t.Fatal("must support ultrafast when reported")
	}
}

func TestMissingAccountDiscoveryDefersRoutesAndTrustedTemplatesStaySeparate(t *testing.T) {
	g := fixtureGateway(t, func(w http.ResponseWriter, _ *http.Request) {
		json.NewEncoder(w).Encode(map[string]any{"models": []model{{"slug": "personal/codex-oauth/m", "canonical_model_id": "m"}, {"slug": "personal/commandcode/m", "canonical_model_id": "m"}}})
	})
	g.cfg.Templates = filepath.Join(t.TempDir(), "templates.json")
	if err := os.WriteFile(g.cfg.Templates, []byte(`{"models":[{"slug":"m","base_instructions":"trusted"},{"slug":"other","base_instructions":"not this scope"}]}`), 0600); err != nil {
		t.Fatal(err)
	}
	out, err := g.refresh(context.Background(), g.cfg.Profiles[1])
	if err != nil {
		t.Fatal(err)
	}
	if len(out.Models) != 1 || len(out.Deferred) != 1 || len(out.Templates) != 1 || out.Templates[0]["base_instructions"] != "trusted" {
		t.Fatal("incorrect deferred/template boundaries")
	}
}

func TestDiscoveryDoesNotFollowRedirect(t *testing.T) {
	hit := false
	target := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { hit = true }))
	defer target.Close()
	g := fixtureGateway(t, func(w http.ResponseWriter, r *http.Request) { http.Redirect(w, r, target.URL, 302) })
	_, err := g.refresh(context.Background(), g.cfg.Profiles[0])
	if err == nil || hit {
		t.Fatal("discovery credentials must not follow redirects")
	}
}

func TestProxyPreservesRequestAndStreaming(t *testing.T) {
	g := fixtureGateway(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/responses" || r.Header.Get("Authorization") != "Bearer fixture" {
			t.Error("proxy modified routing/auth")
		}
		w.Header().Set("Content-Type", "text/event-stream")
		w.Write([]byte("data: fixture\n\n"))
		w.(http.Flusher).Flush()
	})
	r := httptest.NewRequest("POST", "/v1/responses", strings.NewReader(`{"model":"work/litellm/m"}`))
	r.Header.Set("Authorization", "Bearer fixture")
	w := httptest.NewRecorder()
	g.proxy.ServeHTTP(w, r)
	if !w.Flushed || w.Body.String() != "data: fixture\n\n" {
		t.Fatal("stream not forwarded")
	}
}
