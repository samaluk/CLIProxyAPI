package main

import (
	"bytes"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"io"
	"mime"
	"net/http"
	"regexp"
	"strings"
)

// Native Codex image tools send JSON with an unqualified model independently of
// the conversation's selected model. Resolve only administrator-declared aliases
// using the authenticated downstream profile, before CPA enforces its policy.
const maxAliasedImageJSONBytes = 128 << 20

var imageRouteComponent = regexp.MustCompile(`^[a-z0-9][a-z0-9-]{0,63}$`)

func validateImageModelAliases(p profile) error {
	for name, route := range p.ImageModelAliases {
		parts := strings.Split(route, "/")
		if name == "" || strings.TrimSpace(name) != name || strings.Contains(name, "/") ||
			len(parts) != 3 || parts[0] != p.Scope || !imageRouteComponent.MatchString(parts[1]) || parts[2] != name {
			return errors.New("image aliases must preserve the model and use an explicit route in their profile's scope")
		}
	}
	return nil
}

func (g *gateway) requestProfile(r *http.Request) *profile {
	authorization := r.Header.Get("Authorization")
	if !strings.HasPrefix(authorization, "Bearer ") {
		return nil
	}
	key := strings.TrimPrefix(authorization, "Bearer ")
	for i := range g.cfg.Profiles {
		p := &g.cfg.Profiles[i]
		if key != "" && subtle.ConstantTimeCompare([]byte(key), []byte(p.Key)) == 1 {
			return p
		}
	}
	return nil
}

func (g *gateway) serveProxy(w http.ResponseWriter, r *http.Request) {
	p := g.requestProfile(r)
	if p == nil || len(p.ImageModelAliases) == 0 || r.Method != http.MethodPost ||
		(r.URL.Path != "/v1/images/generations" && r.URL.Path != "/v1/images/edits") {
		g.proxy.ServeHTTP(w, r)
		return
	}
	mediaType, _, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
	if err != nil || mediaType != "application/json" || r.Header.Get("Content-Encoding") != "" || r.Body == nil {
		g.proxy.ServeHTTP(w, r)
		return
	}
	if r.ContentLength > maxAliasedImageJSONBytes {
		http.Error(w, "image request body unavailable or too large", http.StatusRequestEntityTooLarge)
		return
	}

	body, err := io.ReadAll(http.MaxBytesReader(w, r.Body, maxAliasedImageJSONBytes))
	_ = r.Body.Close()
	if err != nil {
		status := http.StatusBadRequest
		var tooLarge *http.MaxBytesError
		if errors.As(err, &tooLarge) {
			status = http.StatusRequestEntityTooLarge
		}
		http.Error(w, "image request body unavailable or too large", status)
		return
	}
	var fields map[string]json.RawMessage
	var name string
	if json.Unmarshal(body, &fields) == nil && json.Unmarshal(fields["model"], &name) == nil {
		if route, ok := p.ImageModelAliases[name]; ok {
			fields["model"], _ = json.Marshal(route)
			body, err = json.Marshal(fields)
			if err != nil {
				http.Error(w, "image request could not be encoded", http.StatusBadRequest)
				return
			}
		}
	}
	r.Body = io.NopCloser(bytes.NewReader(body))
	r.ContentLength = int64(len(body))
	r.Header.Del("Content-Length")
	r.TransferEncoding = nil
	g.proxy.ServeHTTP(w, r)
}
