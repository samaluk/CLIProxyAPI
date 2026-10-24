package main

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestImageAliasesPreserveModelAndScope(t *testing.T) {
	for _, route := range []string{
		"work/codex-oauth/gpt-image-2",
		"personal/gpt-image-2",
		"personal/codex-oauth/gpt-image-1.5",
		"personal/../gpt-image-2",
		"personal/codex-oauth/nested/gpt-image-2",
	} {
		t.Run(route, func(t *testing.T) {
			_, err := newGateway(config{
				Listen: ":0", Backend: "http://127.0.0.1:8317", ClientVersion: "fixture",
				Profiles: []profile{{Scope: "personal", Key: "fixture-personal-key-12345", ImageModelAliases: map[string]string{"gpt-image-2": route}}},
			})
			if err == nil {
				t.Fatal("unsafe image alias accepted")
			}
		})
	}
}

func TestNativeImageToolResolvesUsingAuthenticatedProfile(t *testing.T) {
	for _, path := range []string{"/v1/images/generations", "/v1/images/edits"} {
		t.Run(path, func(t *testing.T) {
			g := fixtureGateway(t, func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path != path || r.Header.Get("Authorization") != "Bearer fixture-personal-key-12345" || r.Header.Get("Session-Id") != "native-session" {
					t.Error("routing, credentials or session headers changed")
				}
				body, err := io.ReadAll(r.Body)
				if err != nil {
					t.Fatal(err)
				}
				if r.ContentLength != int64(len(body)) {
					t.Error("rewritten body length is incorrect")
				}
				var fields map[string]json.RawMessage
				if json.Unmarshal(body, &fields) != nil || string(fields["model"]) != `"personal/codex-oauth/gpt-image-2"` || string(fields["seed"]) != "9007199254740993" || string(fields["images"]) != `[{"image_url":"data:image/png;base64,aGk="}]` {
					t.Error("model or image request fields changed incorrectly")
				}
				w.Header().Set("Content-Type", "text/event-stream")
				w.Write([]byte("data: image-result\n\n"))
				w.(http.Flusher).Flush()
			})
			g.cfg.Profiles[1].ImageModelAliases = map[string]string{"gpt-image-2": "personal/codex-oauth/gpt-image-2"}
			r := httptest.NewRequest(http.MethodPost, path, strings.NewReader(`{"model":"gpt-image-2","prompt":"shared workshop","images":[{"image_url":"data:image/png;base64,aGk="}],"seed":9007199254740993,"stream":true}`))
			r.Header.Set("Authorization", "Bearer fixture-personal-key-12345")
			r.Header.Set("Content-Type", "application/json; charset=utf-8")
			r.Header.Set("Session-Id", "native-session")
			w := httptest.NewRecorder()
			g.serveProxy(w, r)
			if w.Code != http.StatusOK || !w.Flushed || w.Body.String() != "data: image-result\n\n" {
				t.Fatalf("image stream not forwarded: %d %q", w.Code, w.Body.String())
			}
		})
	}
}

func TestImageAliasDoesNotChangeOtherRequests(t *testing.T) {
	for _, tc := range []struct {
		name, path, key, contentType, body string
	}{
		{"work has no alias", "/v1/images/generations", "fixture-work-key-12345", "application/json", `{"model":"gpt-image-2","prompt":"test"}`},
		{"unknown key", "/v1/images/generations", "unknown", "application/json", `{"model":"gpt-image-2"}`},
		{"unscoped key", "/v1/images/generations", "", "application/json", `{"model":"gpt-image-2"}`},
		{"explicit work route", "/v1/images/generations", "fixture-personal-key-12345", "application/json", `{"model":"work/litellm/gpt-image-2"}`},
		{"explicit personal route", "/v1/images/generations", "fixture-personal-key-12345", "application/json", `{"model":"personal/codex-oauth/gpt-image-2"}`},
		{"different image model", "/v1/images/generations", "fixture-personal-key-12345", "application/json", `{"model":"gpt-image-1.5"}`},
		{"conversation model", "/v1/responses", "fixture-personal-key-12345", "application/json", `{"model":"gpt-image-2"}`},
		{"multipart edit", "/v1/images/edits", "fixture-personal-key-12345", "multipart/form-data; boundary=test", "--test\r\nunchanged image data\r\n--test--\r\n"},
		{"invalid json", "/v1/images/generations", "fixture-personal-key-12345", "application/json", `{"model":"gpt-image-2"`},
		{"missing model", "/v1/images/generations", "fixture-personal-key-12345", "application/json", `{"prompt":"test"}`},
	} {
		t.Run(tc.name, func(t *testing.T) {
			authorization := ""
			if tc.key != "" {
				authorization = "Bearer " + tc.key
			}
			g := fixtureGateway(t, func(w http.ResponseWriter, r *http.Request) {
				body, _ := io.ReadAll(r.Body)
				if string(body) != tc.body || r.URL.Path != tc.path || r.Header.Get("Authorization") != authorization {
					t.Error("request changed outside its declared image alias")
				}
				w.WriteHeader(http.StatusForbidden)
			})
			g.cfg.Profiles[1].ImageModelAliases = map[string]string{"gpt-image-2": "personal/codex-oauth/gpt-image-2"}
			r := httptest.NewRequest(http.MethodPost, tc.path, strings.NewReader(tc.body))
			r.Header.Set("Authorization", authorization)
			r.Header.Set("Content-Type", tc.contentType)
			w := httptest.NewRecorder()
			g.serveProxy(w, r)
			if w.Code != http.StatusForbidden {
				t.Fatalf("backend policy response changed: %d", w.Code)
			}
		})
	}
}

func TestImageAliasesRemainIndependentAcrossProfiles(t *testing.T) {
	g := fixtureGateway(t, func(w http.ResponseWriter, r *http.Request) {
		var request struct{ Model string }
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
			t.Fatal(err)
		}
		if r.Header.Get("Authorization") == "Bearer fixture-work-key-12345" && request.Model != "work/litellm/gpt-image-2" {
			t.Error("work key resolved to another account or source")
		}
		w.WriteHeader(http.StatusNoContent)
	})
	g.cfg.Profiles[0].ImageModelAliases = map[string]string{"gpt-image-2": "work/litellm/gpt-image-2"}
	g.cfg.Profiles[1].ImageModelAliases = map[string]string{"gpt-image-2": "personal/codex-oauth/gpt-image-2"}
	r := httptest.NewRequest(http.MethodPost, "/v1/images/generations", strings.NewReader(`{"model":"gpt-image-2"}`))
	r.Header.Set("Authorization", "Bearer fixture-work-key-12345")
	r.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	g.serveProxy(w, r)
	if w.Code != http.StatusNoContent {
		t.Fatalf("work route failed: %d", w.Code)
	}
}

type failedImageBody struct{}

func (failedImageBody) Read([]byte) (int, error) { return 0, errors.New("fixture read failure") }
func (failedImageBody) Close() error             { return nil }

func TestImageAliasReadFailureDoesNotReachBackend(t *testing.T) {
	g := fixtureGateway(t, func(http.ResponseWriter, *http.Request) { t.Error("partial image body reached backend") })
	g.cfg.Profiles[1].ImageModelAliases = map[string]string{"gpt-image-2": "personal/codex-oauth/gpt-image-2"}
	r := httptest.NewRequest(http.MethodPost, "/v1/images/generations", nil)
	r.Body = failedImageBody{}
	r.Header.Set("Authorization", "Bearer fixture-personal-key-12345")
	r.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	g.serveProxy(w, r)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("partial image body should be rejected: %d", w.Code)
	}
}

func TestImageAliasDeclaredOversizeDoesNotReadOrForwardBody(t *testing.T) {
	g := fixtureGateway(t, func(http.ResponseWriter, *http.Request) { t.Error("oversized image reached backend") })
	g.cfg.Profiles[1].ImageModelAliases = map[string]string{"gpt-image-2": "personal/codex-oauth/gpt-image-2"}
	r := httptest.NewRequest(http.MethodPost, "/v1/images/edits", nil)
	r.ContentLength = maxAliasedImageJSONBytes + 1
	r.Body = failedImageBody{}
	r.Header.Set("Authorization", "Bearer fixture-personal-key-12345")
	r.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	g.serveProxy(w, r)
	if w.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("declared oversize should be rejected before body reads: %d", w.Code)
	}
}
