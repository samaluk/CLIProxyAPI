package management

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/router-for-me/CLIProxyAPI/v7/internal/config"
	"github.com/router-for-me/CLIProxyAPI/v7/internal/pluginstore"
)

func upgradeRevision(value uint64) *uint64 { return &value }

type upgradeStoreClient struct {
	responses      fakePluginStoreHTTPClient
	artifactURL    string
	beforeArtifact func()
	downloads      int
}

func (client *upgradeStoreClient) Do(req *http.Request) (*http.Response, error) {
	if req.URL.String() == client.artifactURL {
		client.downloads++
		if client.beforeArtifact != nil {
			client.beforeArtifact()
		}
	}
	return client.responses.Do(req)
}

func upgradeStoreFixture(t *testing.T, installedRevision, candidateRevision *uint64, sameVersion, sameArtifact bool) (*Handler, *upgradeStoreClient, pluginstore.Manifest, string) {
	t.Helper()
	const registryURL = "https://registry.example/registry.json"
	const artifactURL = "https://downloads.example/candidate.zip"
	archive := makeManagementPluginStoreZip(t, "sample-provider"+managementPluginExtension(runtime.GOOS), "candidate-library")
	checksum := sha256.Sum256(archive)
	candidate := pluginstore.Plugin{
		ID: "sample-provider", Name: "Sample", Description: "Sample plugin", Author: "tester",
		Version: "0.3.0-review.6330658.20260920", Revision: candidateRevision,
		Install: pluginstore.InstallPlan{Type: pluginstore.InstallTypeDirect, Artifacts: []pluginstore.Artifact{{
			GOOS: runtime.GOOS, GOARCH: runtime.GOARCH, URL: artifactURL, SHA256: hex.EncodeToString(checksum[:]),
		}}},
	}
	installed, errManifest := pluginstore.ManifestFromPlugin(pluginstore.Source{ID: "official", URL: registryURL}, candidate)
	if errManifest != nil {
		t.Fatal(errManifest)
	}
	installed.Revision = installedRevision
	if !sameVersion {
		installed.Version = "0.3.0-review.e87054b.20260920"
	}
	installed.Install.Artifacts = append([]pluginstore.Artifact(nil), installed.Install.Artifacts...)
	if !sameArtifact {
		installed.Install.Artifacts[0].SHA256 = strings.Repeat("a", 64)
	}
	registry, errEncode := json.Marshal(pluginstore.Registry{SchemaVersion: 2, Plugins: []pluginstore.Plugin{candidate}})
	if errEncode != nil {
		t.Fatal(errEncode)
	}
	client := &upgradeStoreClient{responses: fakePluginStoreHTTPClient{registryURL: registry, artifactURL: archive}, artifactURL: artifactURL}
	h := &Handler{
		cfg: &config.Config{Plugins: config.PluginsConfig{Enabled: true, Dir: t.TempDir(), Configs: map[string]config.PluginInstanceConfig{
			"sample-provider": pluginConfigFromYAML(t, "enabled: true\npriority: 7\nmode: retained\n"),
		}}},
		configFilePath: writeTestConfigFile(t), pluginStoreRegistryURL: registryURL, pluginStoreHTTPClient: client,
	}
	if errEnable := h.enablePluginConfigLocked("sample-provider", installed); errEnable != nil {
		t.Fatal(errEnable)
	}
	installedPath := filepath.Join(h.cfg.Plugins.Dir, runtime.GOOS, runtime.GOARCH, "sample-provider-v"+installed.Version+managementPluginExtension(runtime.GOOS))
	if errMkdir := os.MkdirAll(filepath.Dir(installedPath), 0o755); errMkdir != nil {
		t.Fatal(errMkdir)
	}
	data := "installed-library"
	if sameArtifact {
		data = "candidate-library"
	}
	if errWrite := os.WriteFile(installedPath, []byte(data), 0o644); errWrite != nil {
		t.Fatal(errWrite)
	}
	return h, client, installed, installedPath
}

func runUpgradeStoreInstall(h *Handler, upgradeOnly bool) *httptest.ResponseRecorder {
	recorder := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(recorder)
	c.Params = gin.Params{{Key: "id", Value: "sample-provider"}}
	body, _ := json.Marshal(pluginInstallRequest{UpgradeOnly: upgradeOnly})
	c.Request = httptest.NewRequest(http.MethodPost, "/v0/management/plugin-store/sample-provider/install", bytes.NewReader(body))
	h.InstallPluginFromStore(c)
	return recorder
}

func TestPluginStoreUpgradeOnlyRejectsStaleAndUnprovenBeforeDownload(t *testing.T) {
	for _, test := range []struct {
		name          string
		current, next *uint64
		sameVersion   bool
	}{
		{"lower revision", upgradeRevision(2), upgradeRevision(1), false},
		{"equal revision", upgradeRevision(2), upgradeRevision(2), false},
		{"missing installed revision", nil, upgradeRevision(2), false},
		{"missing candidate revision", upgradeRevision(2), nil, false},
		{"same version changed bytes despite newer revision", upgradeRevision(2), upgradeRevision(3), true},
	} {
		t.Run(test.name, func(t *testing.T) {
			h, client, _, path := upgradeStoreFixture(t, test.current, test.next, test.sameVersion, false)
			if !test.sameVersion {
				cachedPath := filepath.Join(filepath.Dir(path), "sample-provider-v0.3.0-review.6330658.20260920"+managementPluginExtension(runtime.GOOS))
				if errWrite := os.WriteFile(cachedPath, []byte("candidate-library"), 0o644); errWrite != nil {
					t.Fatal(errWrite)
				}
			}
			before := marshalPluginRaw(t, h.cfg.Plugins.Configs["sample-provider"])
			recorder := runUpgradeStoreInstall(h, true)
			if recorder.Code != http.StatusConflict || !strings.Contains(recorder.Body.String(), "plugin_store_upgrade_blocked") {
				t.Fatalf("status = %d; body = %s", recorder.Code, recorder.Body.String())
			}
			if client.downloads != 0 {
				t.Fatalf("downloaded rejected update %d times", client.downloads)
			}
			if after := marshalPluginRaw(t, h.cfg.Plugins.Configs["sample-provider"]); after != before {
				t.Fatal("rejected install changed configuration")
			}
			data, errRead := os.ReadFile(path)
			if errRead != nil || string(data) != "installed-library" {
				t.Fatalf("installed file changed: %s, %v", data, errRead)
			}
		})
	}
}

func TestPluginStoreUpgradeOnlyAcceptsNewRevisionAndPreservesReinstallFloor(t *testing.T) {
	for _, test := range []struct {
		name          string
		current, next *uint64
		same          bool
		wantRevision  uint64
	}{
		{"newer revision despite lower hash", upgradeRevision(1), upgradeRevision(2), false, 2},
		{"identical legacy revision seed", nil, upgradeRevision(2), true, 2},
		{"stale identical reinstall retains floor", upgradeRevision(2), upgradeRevision(1), true, 2},
		{"missing revision identical reinstall retains floor", upgradeRevision(2), nil, true, 2},
	} {
		t.Run(test.name, func(t *testing.T) {
			h, client, _, _ := upgradeStoreFixture(t, test.current, test.next, test.same, test.same)
			reloads, reloadDone := captureConfigReload(h)
			recorder := runUpgradeStoreInstall(h, true)
			if recorder.Code != http.StatusOK {
				t.Fatalf("status = %d; body = %s", recorder.Code, recorder.Body.String())
			}
			waitForAsyncReload(t, reloads)
			waitForReloadDone(t, reloadDone)
			manifest := pluginStoreManifestFromConfig(t, h.cfg.Plugins.Configs["sample-provider"])
			if manifest.Revision == nil || *manifest.Revision != test.wantRevision {
				t.Fatalf("revision = %v; want %d", manifest.Revision, test.wantRevision)
			}
			if client.downloads != 1 {
				t.Fatalf("downloads = %d; want 1", client.downloads)
			}
			if raw := marshalPluginRaw(t, h.cfg.Plugins.Configs["sample-provider"]); !strings.Contains(raw, "mode: retained") || h.cfg.Plugins.Configs["sample-provider"].Priority != 7 {
				t.Fatal("plugin settings changed")
			}
		})
	}
}

func TestPluginStoreUpgradeOnlyRechecksBeforeFileCommit(t *testing.T) {
	h, client, current, _ := upgradeStoreFixture(t, upgradeRevision(1), upgradeRevision(2), false, false)
	var newerPath string
	var selectedConfig string
	client.beforeArtifact = func() {
		// A concurrent configuration update selected the target version with
		// newer bytes while the older update was downloading its archive.
		newer := current
		newer.Version = "0.3.0-review.6330658.20260920"
		newer.Revision = upgradeRevision(3)
		newer.Install.Artifacts[0].SHA256 = strings.Repeat("c", 64)
		newerPath = filepath.Join(h.cfg.Plugins.Dir, runtime.GOOS, runtime.GOARCH, "sample-provider-v"+newer.Version+managementPluginExtension(runtime.GOOS))
		h.mu.Lock()
		defer h.mu.Unlock()
		if errWrite := os.WriteFile(newerPath, []byte("newer-selected-library"), 0o644); errWrite != nil {
			t.Fatal(errWrite)
		}
		if errEnable := h.enablePluginConfigLocked("sample-provider", newer); errEnable != nil {
			t.Fatal(errEnable)
		}
		selectedConfig = marshalPluginRaw(t, h.cfg.Plugins.Configs["sample-provider"])
	}
	recorder := runUpgradeStoreInstall(h, true)
	if recorder.Code != http.StatusConflict {
		t.Fatalf("status = %d; body = %s", recorder.Code, recorder.Body.String())
	}
	if client.downloads != 1 {
		t.Fatalf("downloads = %d; want 1", client.downloads)
	}
	data, errRead := os.ReadFile(newerPath)
	if errRead != nil || string(data) != "newer-selected-library" {
		t.Fatalf("stale install replaced selected bytes: %s, %v", data, errRead)
	}
	if raw := marshalPluginRaw(t, h.cfg.Plugins.Configs["sample-provider"]); raw != selectedConfig {
		t.Fatal("stale install replaced selected manifest or settings")
	}
}

func TestPluginStoreExplicitRollbackStillAllowed(t *testing.T) {
	h, _, _, _ := upgradeStoreFixture(t, upgradeRevision(2), upgradeRevision(1), false, false)
	reloads, reloadDone := captureConfigReload(h)
	recorder := runUpgradeStoreInstall(h, false)
	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d; body = %s", recorder.Code, recorder.Body.String())
	}
	waitForAsyncReload(t, reloads)
	waitForReloadDone(t, reloadDone)
	manifest := pluginStoreManifestFromConfig(t, h.cfg.Plugins.Configs["sample-provider"])
	if manifest.Revision == nil || *manifest.Revision != 1 {
		t.Fatalf("explicit rollback revision = %v; want 1", manifest.Revision)
	}
}

func TestListPluginStoreExposesUpgradeDecisionAndRevisions(t *testing.T) {
	for _, next := range []uint64{1, 3} {
		h, _, _, _ := upgradeStoreFixture(t, upgradeRevision(2), upgradeRevision(next), false, false)
		recorder := httptest.NewRecorder()
		c, _ := gin.CreateTestContext(recorder)
		c.Request = httptest.NewRequest(http.MethodGet, "/v0/management/plugin-store", nil)
		h.ListPluginStore(c)
		var result pluginStoreListResponse
		if errDecode := json.Unmarshal(recorder.Body.Bytes(), &result); errDecode != nil {
			t.Fatal(errDecode)
		}
		if recorder.Code != http.StatusOK || len(result.Plugins) != 1 {
			t.Fatalf("status = %d; body = %s", recorder.Code, recorder.Body.String())
		}
		entry := result.Plugins[0]
		if entry.Revision == nil || *entry.Revision != next || entry.InstalledRevision == nil || *entry.InstalledRevision != 2 {
			t.Fatalf("missing revision metadata: %#v", entry)
		}
		if entry.UpgradeAllowed != (next > 2) || (entry.UpgradeBlockReason == "") != entry.UpgradeAllowed {
			t.Fatalf("unexpected upgrade decision: %#v", entry)
		}
		if entry.UpdateAvailable != (next > 2) {
			t.Fatalf("update_available ignored declared revisions: %#v", entry)
		}
	}
}

func TestPluginStoreHistoricalVersionRetainsItsOwnRevision(t *testing.T) {
	plugin := pluginstore.Plugin{ID: "sample", Name: "Sample", Description: "Sample", Author: "tester", Version: "2.0.0", Revision: upgradeRevision(2), Install: pluginstore.InstallPlan{Type: pluginstore.InstallTypeDirect, Artifacts: []pluginstore.Artifact{{GOOS: "linux", GOARCH: "amd64", URL: "https://downloads.example/sample.zip", SHA256: strings.Repeat("a", 64)}}}}
	plugin.Versions = []pluginstore.Version{{Version: "1.0.0", Revision: upgradeRevision(1), Install: plugin.Install}}
	manifest, errManifest := pluginStoreDirectManifest(pluginstore.DefaultSource(), plugin, "1.0.0")
	if errManifest != nil {
		t.Fatal(errManifest)
	}
	if manifest.Revision == nil || *manifest.Revision != 1 {
		t.Fatalf("historical revision = %v; want 1", manifest.Revision)
	}
}
