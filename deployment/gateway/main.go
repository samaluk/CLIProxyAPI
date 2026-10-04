// gateway serves account-scoped catalog snapshots and proxies the existing CPA
// API, including streaming and WebSocket traffic, through one tailnet origin.
package main

import (
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"
)

type model map[string]any
type profile struct {
	Scope string `json:"scope"`
	Key   string `json:"key"`
}
type config struct {
	Listen        string    `json:"listen"`
	Backend       string    `json:"backend"`
	AuthDir       string    `json:"auth_dir"`
	Templates     string    `json:"templates"`
	ClientVersion string    `json:"codex_client_version"`
	Profiles      []profile `json:"profiles"`
}
type snapshot struct {
	Schema     int               `json:"schema"`
	Scope      string            `json:"scope"`
	Revision   string            `json:"revision"`
	ObservedAt string            `json:"observed_at"`
	Models     []model           `json:"models"`
	Templates  []model           `json:"templates"`
	Sources    map[string]string `json:"sources"`
	Deferred   []string          `json:"deferred"`
}
type cached struct {
	value snapshot
	at    time.Time
}
type gateway struct {
	cfg    config
	client *http.Client
	proxy  http.Handler
	mu     sync.Mutex
	cache  map[string]cached
}

// These are data fields. Model prompts from the generic proxy never enter a
// client's system instructions. Native templates are a separate trusted file.
var capabilityFields = []string{"canonical_model_id", "context_window", "max_context_window", "max_tokens", "max_output_tokens", "max_completion_tokens", "input_modalities", "supported_input_modalities", "output_modalities", "supported_reasoning_levels", "default_reasoning_level", "service_tiers", "additional_speed_tiers", "supports_parallel_tool_calls", "supports_image_detail_original", "support_verbosity"}

func safeModel(input model) model {
	out := model{"slug": input["slug"]}
	for _, key := range capabilityFields {
		if value, ok := input[key]; ok {
			out[key] = value
		}
	}
	if levels, ok := out["supported_reasoning_levels"].([]any); ok {
		clean := []any{}
		for _, item := range levels {
			if level, ok := item.(map[string]any); ok {
				if effort, ok := level["effort"].(string); ok {
					clean = append(clean, model{"effort": effort, "description": effort})
				}
			}
		}
		out["supported_reasoning_levels"] = clean
	}
	if tiers, ok := out["service_tiers"].([]any); ok {
		clean := []any{}
		for _, item := range tiers {
			if tier, ok := item.(map[string]any); ok {
				if id, ok := tier["id"].(string); ok {
					clean = append(clean, model{"id": id})
				}
			}
		}
		out["service_tiers"] = clean
	}
	return out
}

func mergeCapabilities(base, account model) {
	for key, value := range safeModel(account) {
		if key != "slug" && key != "canonical_model_id" {
			base[key] = value
		}
	}
	for _, key := range []string{"max_tokens", "max_output_tokens", "max_completion_tokens"} {
		if value, ok := account[key]; ok {
			base["max_tokens"], base["max_output_tokens"], base["max_completion_tokens"] = value, value, value
			break
		}
	}
	for _, key := range []string{"input_modalities", "supported_input_modalities"} {
		if value, ok := account[key]; ok {
			base["input_modalities"], base["supported_input_modalities"] = value, value
			break
		}
	}
	if _, ok := account["additional_speed_tiers"]; !ok {
		if tiers, ok := account["service_tiers"].([]any); ok {
			speeds := []string{}
			fast, ultra := false, false
			for _, item := range tiers {
				if tier, ok := item.(map[string]any); ok {
					fast = fast || tier["id"] == "priority" || tier["id"] == "fast"
					ultra = ultra || tier["id"] == "ultrafast"
				}
			}
			if fast {
				speeds = append(speeds, "fast")
			}
			if ultra {
				speeds = append(speeds, "ultrafast")
			}
			base["additional_speed_tiers"] = speeds
		}
	}
	if levels, ok := account["supported_reasoning_levels"].([]any); ok {
		valid := false
		for _, item := range levels {
			if level, ok := item.(map[string]any); ok && level["effort"] == base["default_reasoning_level"] {
				valid = true
			}
		}
		if !valid {
			base["default_reasoning_level"] = nil
		}
	}
}

func (g *gateway) get(ctx context.Context, address string, headers map[string]string, result any) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, address, nil)
	if err != nil {
		return errors.New("invalid discovery request")
	}
	for key, value := range headers {
		req.Header.Set(key, value)
	}
	res, err := g.client.Do(req)
	if err != nil {
		return errors.New("discovery transport unavailable")
	}
	defer res.Body.Close()
	if res.StatusCode != http.StatusOK {
		return fmt.Errorf("discovery HTTP %d", res.StatusCode)
	}
	return json.NewDecoder(io.LimitReader(res.Body, 32<<20)).Decode(result)
}

func (g *gateway) accountModels(ctx context.Context, scope string) map[string]model {
	result := map[string]model{}
	owners := map[string]int{}
	entries, err := os.ReadDir(g.cfg.AuthDir)
	if err != nil {
		return result
	}
	for _, entry := range entries {
		if entry.IsDir() || entry.Type()&os.ModeSymlink != 0 || !strings.HasSuffix(entry.Name(), ".json") {
			continue
		}
		data, err := os.ReadFile(filepath.Join(g.cfg.AuthDir, entry.Name()))
		if err != nil {
			continue
		}
		var auth struct {
			Type     string `json:"type"`
			Prefix   string `json:"prefix"`
			Disabled bool   `json:"disabled"`
			Account  string `json:"account_id"`
			Token    string `json:"access_token"`
			Aliases  []struct {
				Name  string `json:"name"`
				Alias string `json:"alias"`
			} `json:"model_aliases"`
		}
		if json.Unmarshal(data, &auth) != nil || auth.Disabled || auth.Type != "codex" || auth.Prefix != scope || auth.Account == "" || auth.Token == "" {
			continue
		}
		// A route with multiple credentials does not establish which account
		// the scheduler will use. Defer it instead of publishing one account's
		// entitlements as if they applied to all eligible credentials.
		for _, alias := range auth.Aliases {
			if strings.HasPrefix(alias.Alias, "codex-oauth/") {
				owners[scope+"/"+alias.Alias]++
			}
		}
		var native struct {
			Models []model `json:"models"`
		}
		address := "https://chatgpt.com/backend-api/codex/models?" + url.Values{"client_version": {g.cfg.ClientVersion}}.Encode()
		headers := map[string]string{"Authorization": "Bearer " + auth.Token, "ChatGPT-Account-Id": auth.Account, "User-Agent": "codex_cli_rs/" + g.cfg.ClientVersion, "originator": "codex_cli_rs"}
		if g.get(ctx, address, headers, &native) != nil {
			continue
		}
		byID := map[string]model{}
		for _, m := range native.Models {
			if id, ok := m["slug"].(string); ok {
				byID[id] = m
			}
		}
		for _, alias := range auth.Aliases {
			if m, ok := byID[alias.Name]; ok && strings.HasPrefix(alias.Alias, "codex-oauth/") {
				result[scope+"/"+alias.Alias] = m
			}
		}
	}
	for route, count := range owners {
		if count != 1 {
			delete(result, route)
		}
	}
	return result
}

func (g *gateway) refresh(ctx context.Context, p profile) (snapshot, error) {
	var response struct {
		Models []model `json:"models"`
	}
	if err := g.get(ctx, strings.TrimRight(g.cfg.Backend, "/")+"/v1/models?client_version=pi", map[string]string{"Authorization": "Bearer " + p.Key}, &response); err != nil {
		return snapshot{}, err
	}
	if len(response.Models) == 0 {
		return snapshot{}, errors.New("empty gateway catalog")
	}
	account := g.accountModels(ctx, p.Scope)
	out := snapshot{Schema: 1, Scope: p.Scope, ObservedAt: time.Now().UTC().Format(time.RFC3339), Models: []model{}, Templates: []model{}, Sources: map[string]string{}, Deferred: []string{}}
	canonical := map[string]bool{}
	seen := map[string]bool{}
	for _, raw := range response.Models {
		id, ok := raw["slug"].(string)
		if !ok || !strings.HasPrefix(id, p.Scope+"/") {
			continue
		}
		if seen[id] {
			return snapshot{}, errors.New("duplicate gateway route")
		}
		seen[id] = true
		m := safeModel(raw)
		source := "proxy metadata; undiscovered fields retain client fallback"
		if strings.HasPrefix(id, p.Scope+"/codex-oauth/") {
			fresh, ok := account[id]
			if !ok {
				out.Deferred = append(out.Deferred, id)
				continue
			}
			mergeCapabilities(m, fresh)
			source = "authenticated Codex account; other fields use proxy fallback"
		}
		out.Models = append(out.Models, m)
		out.Sources[id] = source
		if identity, ok := m["canonical_model_id"].(string); ok {
			canonical[identity] = true
		}
	}
	if len(out.Models) == 0 {
		return snapshot{}, errors.New("no verified scope routes")
	}
	if g.cfg.Templates != "" {
		var trusted struct {
			Models []model `json:"models"`
		}
		data, err := os.ReadFile(g.cfg.Templates)
		if err != nil {
			return snapshot{}, errors.New("trusted templates unavailable")
		}
		if json.Unmarshal(data, &trusted) != nil {
			return snapshot{}, errors.New("trusted templates invalid")
		}
		for _, m := range trusted.Models {
			if id, ok := m["slug"].(string); ok && canonical[id] {
				out.Templates = append(out.Templates, m)
			}
		}
	}
	sort.Slice(out.Models, func(i, j int) bool { return out.Models[i]["slug"].(string) < out.Models[j]["slug"].(string) })
	sort.Strings(out.Deferred)
	stable, err := json.Marshal([]any{out.Scope, out.Models, out.Templates, out.Sources, out.Deferred})
	if err != nil {
		return snapshot{}, errors.New("invalid catalog")
	}
	digest := sha256.Sum256(stable)
	out.Revision = hex.EncodeToString(digest[:])
	return out, nil
}

func (g *gateway) serveCatalog(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "private, no-cache")
	w.Header().Set("Vary", "Authorization")
	if r.Method != http.MethodGet {
		http.Error(w, "GET required", http.StatusMethodNotAllowed)
		return
	}
	key := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
	var selected *profile
	for _, p := range g.cfg.Profiles {
		if key != "" && subtle.ConstantTimeCompare([]byte(key), []byte(p.Key)) == 1 {
			copy := p
			selected = &copy
			break
		}
	}
	if selected == nil {
		http.Error(w, "valid scoped gateway key required", http.StatusUnauthorized)
		return
	}
	g.mu.Lock()
	defer g.mu.Unlock()
	entry, found := g.cache[selected.Scope]
	if !found || time.Since(entry.at) >= time.Minute {
		ctx, cancel := context.WithTimeout(r.Context(), 40*time.Second)
		defer cancel()
		value, err := g.refresh(ctx, *selected)
		if err != nil {
			http.Error(w, "catalog refresh unavailable; retain the last client catalog", http.StatusServiceUnavailable)
			return
		}
		entry = cached{value: value, at: time.Now()}
		g.cache[selected.Scope] = entry
	}
	etag := `"` + entry.value.Revision + `"`
	w.Header().Set("ETag", etag)
	if r.Header.Get("If-None-Match") == etag {
		w.WriteHeader(http.StatusNotModified)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(entry.value); err != nil {
		log.Print("catalog response interrupted")
	}
}

func newGateway(cfg config) (*gateway, error) {
	backend, err := url.Parse(cfg.Backend)
	if err != nil || backend.Scheme != "http" || backend.Host == "" || backend.User != nil || backend.RawQuery != "" || backend.Fragment != "" || backend.Path != "" {
		return nil, errors.New("explicit internal HTTP backend required")
	}
	if cfg.Listen == "" || cfg.ClientVersion == "" || len(cfg.Profiles) == 0 {
		return nil, errors.New("listen, client version and profiles required")
	}
	keys := map[string]bool{}
	scopes := map[string]bool{}
	for _, p := range cfg.Profiles {
		if (p.Scope != "personal" && p.Scope != "work") || len(p.Key) < 16 || keys[p.Key] || scopes[p.Scope] {
			return nil, errors.New("unique personal/work scoped keys required")
		}
		keys[p.Key], scopes[p.Scope] = true, true
	}
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.Proxy = nil
	proxy := httputil.NewSingleHostReverseProxy(backend)
	proxy.Transport = transport
	proxy.FlushInterval = -1
	proxy.ErrorHandler = func(w http.ResponseWriter, _ *http.Request, _ error) {
		http.Error(w, "gateway backend unavailable", http.StatusBadGateway)
	}
	return &gateway{cfg: cfg, client: &http.Client{Transport: transport, CheckRedirect: func(_ *http.Request, _ []*http.Request) error { return http.ErrUseLastResponse }}, proxy: proxy, cache: map[string]cached{}}, nil
}

func main() {
	path := flag.String("config", "/data/gateway.json", "private gateway config")
	flag.Parse()
	data, err := os.ReadFile(*path)
	if err != nil {
		log.Print("gateway config unavailable")
		os.Exit(1)
	}
	var cfg config
	if json.Unmarshal(data, &cfg) != nil {
		log.Print("gateway config invalid")
		os.Exit(1)
	}
	g, err := newGateway(cfg)
	if err != nil {
		log.Print(err)
		os.Exit(1)
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/catalog/v1", g.serveCatalog)
	mux.Handle("/", g.proxy)
	server := &http.Server{Addr: cfg.Listen, Handler: mux, ReadHeaderTimeout: 15 * time.Second, MaxHeaderBytes: 1 << 20}
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Print("gateway listener stopped")
		os.Exit(1)
	}
}
