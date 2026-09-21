package pluginstore

import (
	"encoding/json"
	"strings"
	"testing"

	"gopkg.in/yaml.v3"
)

func revisionPointer(value uint64) *uint64 { return &value }

func directUpgradeManifest(version, checksum string, revision *uint64) Manifest {
	return Manifest{
		SchemaVersion: SchemaVersionV2, ID: "sample", Name: "Sample", Description: "Sample plugin", Author: "tester",
		Version: version, Revision: revision, SourceID: "reviewed", SourceURL: "https://registry.example/plugins.json",
		Install: InstallPlan{Type: InstallTypeDirect, Artifacts: []Artifact{{
			GOOS: "darwin", GOARCH: "arm64", URL: "https://downloads.example/sample.zip", SHA256: checksum,
		}}},
	}
}

func TestUpgradeManifestDirect(t *testing.T) {
	for _, test := range []struct {
		name                            string
		installedVersion, nextVersion   string
		installedRevision, nextRevision *uint64
		sameArtifact                    bool
		wantAllowed                     bool
		wantRevision                    uint64
	}{
		{"newer revision ignores hash order", "0.3.0-review.e87054b.20260920", "0.3.0-review.6330658.20260920", revisionPointer(1), revisionPointer(2), false, true, 2},
		{"stale registry", "0.3.0-review.e87054b.20260920", "0.3.0-review.6330658.20260920", revisionPointer(2), revisionPointer(1), false, false, 0},
		{"equal revision changed artifact", "1.0.0", "1.0.1", revisionPointer(2), revisionPointer(2), false, false, 0},
		{"equal revision same version changed artifact", "1.0.0", "1.0.0", revisionPointer(2), revisionPointer(2), false, false, 0},
		{"newer revision cannot replace same version bytes", "1.0.0", "1.0.0", revisionPointer(2), revisionPointer(3), false, false, 0},
		{"missing installed revision", "1.0.0", "1.0.1", nil, revisionPointer(2), false, false, 0},
		{"missing candidate revision", "1.0.0", "1.0.1", revisionPointer(2), nil, false, false, 0},
		{"same artifact seeds legacy revision", "1.0.0", "1.0.0", nil, revisionPointer(2), true, true, 2},
		{"same artifact retains floor", "1.0.0", "1.0.0", revisionPointer(2), revisionPointer(1), true, true, 2},
		{"same artifact missing revision retains floor", "1.0.0", "1.0.0", revisionPointer(2), nil, true, true, 2},
		{"legacy identical reinstall", "1.0.0", "1.0.0", nil, nil, true, true, 0},
		{"same bytes different label is not identical reinstall", "1.0.0", "0.9.0", revisionPointer(2), revisionPointer(1), true, false, 0},
	} {
		t.Run(test.name, func(t *testing.T) {
			installed := directUpgradeManifest(test.installedVersion, strings.Repeat("a", 64), test.installedRevision)
			checksum := strings.Repeat("b", 64)
			if test.sameArtifact {
				checksum = installed.Install.Artifacts[0].SHA256
			}
			candidate := directUpgradeManifest(test.nextVersion, checksum, test.nextRevision)
			result, errUpgrade := UpgradeManifest(installed, candidate, "darwin", "arm64")
			if (errUpgrade == nil) != test.wantAllowed {
				t.Fatalf("UpgradeManifest() error = %v, allowed = %v", errUpgrade, test.wantAllowed)
			}
			if test.wantAllowed && test.wantRevision > 0 && (result.Revision == nil || *result.Revision != test.wantRevision) {
				t.Fatalf("revision = %v, want %d", result.Revision, test.wantRevision)
			}
		})
	}
}

func TestUpgradeManifestRejectsUnknownProvenance(t *testing.T) {
	installed := directUpgradeManifest("1.0.0", strings.Repeat("a", 64), revisionPointer(1))
	candidate := directUpgradeManifest("1.0.1", strings.Repeat("b", 64), revisionPointer(2))
	for _, mutate := range []func(*Manifest){
		func(m *Manifest) { m.SourceURL = "https://other.example/plugins.json" },
		func(m *Manifest) { m.SourceID = "other" },
		func(m *Manifest) { m.ID = "different" },
		func(m *Manifest) { m.Revision = revisionPointer(0) },
		func(m *Manifest) { m.Install.Artifacts = nil; m.SourceURL = "" },
	} {
		changed := installed
		mutate(&changed)
		if _, errUpgrade := UpgradeManifest(changed, candidate, "darwin", "arm64"); errUpgrade == nil {
			t.Fatal("invalid or different provenance accepted")
		}
	}
	if _, errUpgrade := UpgradeManifest(installed, candidate, "linux", "amd64"); errUpgrade == nil {
		t.Fatal("unavailable platform accepted")
	}
}

func TestCompareReleaseVersions(t *testing.T) {
	for _, test := range []struct {
		installed, candidate string
		order                int
		comparable           bool
	}{
		{"1.2.3", "1.2.4", -1, true}, {"v1.2.4", "1.2.3", 1, true},
		{"1.0.0-alpha.1", "1.0.0-beta.1", -1, true}, {"1.0.0-rc.1", "1.0.0-rc.2", -1, true},
		{"1.0.0-1", "1.0.0-2", -1, true}, {"1.0.0-1", "1.0.0-alpha", -1, true},
		{"1.0.0-rc.2", "1.0.0-rc.1", 1, true}, {"1.0.0-rc.1", "1.0.0", -1, true},
		{"1.0.0", "1.0.0-rc.1", 1, true}, {"1.0.0+build1", "1.0.0+build2", 0, true},
		{"1.0.0-review.fff0000", "1.0.0-review.aaa0000", 0, false},
		{"1.0.0-review.aaa0000", "1.0.0-review.fff0000", 0, false},
		{"1.0", "1.0.1", 0, false}, {"01.0.0", "1.0.1", 0, false},
		{"1.0.0-rc.01", "1.0.0", 0, false}, {"1.0.0+", "1.0.1", 0, false},
	} {
		order, comparable := compareReleaseVersions(test.installed, test.candidate)
		if order != test.order || comparable != test.comparable {
			t.Fatalf("compareReleaseVersions(%q, %q) = %d, %v; want %d, %v", test.installed, test.candidate, order, comparable, test.order, test.comparable)
		}
	}
}

func TestUpgradeManifestGitHubUsesReleaseOrder(t *testing.T) {
	plugin := Plugin{ID: "sample", Name: "Sample", Description: "Sample plugin", Author: "tester", Repository: "https://github.com/example/sample"}
	source := Source{ID: "official", URL: "https://registry.example/plugins.json"}
	installed, errInstalled := ManifestFromRelease(source, plugin, Release{TagName: "v1.0.0"})
	if errInstalled != nil {
		t.Fatal(errInstalled)
	}
	for _, version := range []string{"v0.9.0", "v1.0.0", "v1.0.1"} {
		candidate, errCandidate := ManifestFromRelease(source, plugin, Release{TagName: version})
		if errCandidate != nil {
			t.Fatal(errCandidate)
		}
		_, errUpgrade := UpgradeManifest(installed, candidate, "darwin", "arm64")
		if (errUpgrade == nil) != (version == "v1.0.1") {
			t.Fatalf("version %s error = %v", version, errUpgrade)
		}
	}
}

func TestDirectRevisionRoundTripAndValidation(t *testing.T) {
	manifest := directUpgradeManifest("1.0.0", strings.Repeat("a", 64), revisionPointer(123))
	plugin := manifest.Plugin()
	encoded, errEncode := json.Marshal(Registry{SchemaVersion: SchemaVersionV2, Plugins: []Plugin{plugin}})
	if errEncode != nil {
		t.Fatal(errEncode)
	}
	parsed, errParse := ParseRegistry(encoded)
	if errParse != nil {
		t.Fatal(errParse)
	}
	restored, errManifest := ManifestFromPlugin(Source{ID: manifest.SourceID, URL: manifest.SourceURL}, parsed.Plugins[0])
	if errManifest != nil {
		t.Fatal(errManifest)
	}
	yamlData, errYAML := yaml.Marshal(restored)
	if errYAML != nil {
		t.Fatal(errYAML)
	}
	var decoded Manifest
	if errDecode := yaml.Unmarshal(yamlData, &decoded); errDecode != nil {
		t.Fatal(errDecode)
	}
	if decoded.Revision == nil || *decoded.Revision != 123 {
		t.Fatalf("revision round trip = %v", decoded.Revision)
	}
	for _, revision := range []uint64{0, maxRevision + 1} {
		invalid := plugin
		invalid.Revision = revisionPointer(revision)
		if errValidate := ValidatePlugin(invalid); errValidate == nil {
			t.Fatalf("invalid revision %d accepted", revision)
		}
		invalid = plugin
		invalid.Versions = []Version{{Version: "0.9.0", Revision: revisionPointer(revision), Install: plugin.Install}}
		if errValidate := ValidatePlugin(invalid); errValidate == nil {
			t.Fatalf("invalid historical revision %d accepted", revision)
		}
	}
}
