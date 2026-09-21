package pluginstore

import (
	"fmt"
	"strconv"
	"strings"
)

// Revisions cross JSON into browser clients, so they must remain exact there.
const maxRevision = uint64(1<<53 - 1)

func validateRevision(revision *uint64) error {
	if revision != nil && (*revision == 0 || *revision > maxRevision) {
		return fmt.Errorf("revision must be a positive safe integer")
	}
	return nil
}

// UpgradeManifest checks an opt-in automatic update against the currently
// selected store manifest. Explicit version installs do not use this guard.
// The returned manifest retains a revision floor on an identical reinstall.
func UpgradeManifest(installed, candidate Manifest, goos, goarch string) (Manifest, error) {
	if errValidate := candidate.Validate(); errValidate != nil {
		return Manifest{}, fmt.Errorf("candidate manifest: %w", errValidate)
	}
	if errValidate := installed.Validate(); errValidate != nil {
		return Manifest{}, fmt.Errorf("installed provenance unavailable: %w", errValidate)
	}
	if installed.ID != candidate.ID || strings.TrimSpace(installed.SourceURL) == "" ||
		strings.TrimSpace(installed.SourceURL) != strings.TrimSpace(candidate.SourceURL) ||
		(strings.TrimSpace(installed.SourceID) != "" && strings.TrimSpace(installed.SourceID) != strings.TrimSpace(candidate.SourceID)) {
		return Manifest{}, fmt.Errorf("installed source does not match the update source")
	}
	if installed.InstallType() != candidate.InstallType() {
		return Manifest{}, fmt.Errorf("automatic update cannot change install type")
	}
	if candidate.InstallType() == InstallTypeDirect {
		currentArtifact, errCurrent := SelectArtifact(installed.Install, goos, goarch)
		nextArtifact, errNext := SelectArtifact(candidate.Install, goos, goarch)
		if errNext != nil {
			return Manifest{}, errNext
		}
		if normalizeVersion(installed.Version) == normalizeVersion(candidate.Version) {
			if errCurrent != nil || !strings.EqualFold(currentArtifact.SHA256, nextArtifact.SHA256) {
				return Manifest{}, fmt.Errorf("same version has different or unverified artifact bytes; publish a unique version")
			}
			if installed.Revision != nil && (candidate.Revision == nil || *candidate.Revision < *installed.Revision) {
				candidate.Revision = installed.Revision
			}
			return candidate, nil
		}
		if installed.Revision == nil || candidate.Revision == nil {
			return Manifest{}, fmt.Errorf("automatic update requires installed and candidate revisions; use an explicit version install to establish provenance")
		}
		if *candidate.Revision <= *installed.Revision {
			return Manifest{}, fmt.Errorf("candidate revision must be newer than the installed revision")
		}
		return candidate, nil
	}
	if strings.TrimSpace(installed.Repository) != strings.TrimSpace(candidate.Repository) {
		return Manifest{}, fmt.Errorf("automatic update cannot change the release repository")
	}
	comparison, comparable := compareReleaseVersions(installed.Version, candidate.Version)
	if !comparable {
		return Manifest{}, fmt.Errorf("release version order is unproven; use an explicit version install")
	}
	if comparison >= 0 {
		return Manifest{}, fmt.Errorf("candidate release must be newer; use an explicit version install for reinstall or rollback")
	}
	return candidate, nil
}

type releaseVersion struct {
	core [3]uint64
	pre  string
}

// Stable SemVer numbers and conventional numbered prereleases have meaningful
// release order. Opaque prerelease names, especially commit hashes, do not tell
// us which build was published later and must not use lexical ordering.
func compareReleaseVersions(installed, candidate string) (int, bool) {
	a, okA := parseReleaseVersion(installed)
	b, okB := parseReleaseVersion(candidate)
	if !okA || !okB {
		return 0, false
	}
	for i := range a.core {
		if a.core[i] < b.core[i] {
			return -1, true
		}
		if a.core[i] > b.core[i] {
			return 1, true
		}
	}
	if a.pre == b.pre {
		return 0, true
	}
	if a.pre == "" {
		return 1, true
	}
	if b.pre == "" {
		return -1, true
	}
	stageA, numbersA, orderedA := numberedPrerelease(a.pre)
	stageB, numbersB, orderedB := numberedPrerelease(b.pre)
	if !orderedA || !orderedB {
		return 0, false
	}
	if stageA < stageB {
		return -1, true
	}
	if stageA > stageB {
		return 1, true
	}
	for i := 0; i < len(numbersA) && i < len(numbersB); i++ {
		if numbersA[i] < numbersB[i] {
			return -1, true
		}
		if numbersA[i] > numbersB[i] {
			return 1, true
		}
	}
	if len(numbersA) < len(numbersB) {
		return -1, true
	}
	if len(numbersA) > len(numbersB) {
		return 1, true
	}
	return 0, true
}

func parseReleaseVersion(value string) (releaseVersion, bool) {
	var parsed releaseVersion
	version := normalizeVersion(value)
	parts := strings.Split(version, "+")
	if len(parts) > 2 || (len(parts) == 2 && !validReleaseIdentifiers(parts[1], false)) {
		return parsed, false
	}
	parts = strings.SplitN(parts[0], "-", 2)
	if len(parts) == 2 {
		parsed.pre = parts[1]
		if !validReleaseIdentifiers(parsed.pre, true) {
			return parsed, false
		}
	}
	core := strings.Split(parts[0], ".")
	if len(core) != 3 {
		return parsed, false
	}
	for i, segment := range core {
		number, okNumber := canonicalReleaseNumber(segment)
		if !okNumber {
			return parsed, false
		}
		parsed.core[i] = number
	}
	return parsed, true
}

func canonicalReleaseNumber(value string) (uint64, bool) {
	if value == "" || (len(value) > 1 && value[0] == '0') {
		return 0, false
	}
	for _, ch := range value {
		if ch < '0' || ch > '9' {
			return 0, false
		}
	}
	number, errParse := strconv.ParseUint(value, 10, 64)
	return number, errParse == nil
}

func validReleaseIdentifiers(value string, prerelease bool) bool {
	for _, identifier := range strings.Split(value, ".") {
		if identifier == "" {
			return false
		}
		numeric := true
		for _, ch := range identifier {
			if !((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') || ch == '-') {
				return false
			}
			numeric = numeric && ch >= '0' && ch <= '9'
		}
		if prerelease && numeric && len(identifier) > 1 && identifier[0] == '0' {
			return false
		}
	}
	return true
}

func numberedPrerelease(value string) (int, []uint64, bool) {
	parts := strings.Split(value, ".")
	stage := map[string]int{"alpha": 0, "beta": 1, "rc": 2}
	rank, okRank := stage[parts[0]]
	numericParts := parts[1:]
	if !okRank {
		if _, numeric := canonicalReleaseNumber(parts[0]); !numeric {
			return 0, nil, false
		}
		rank = -1
		numericParts = parts
	}
	numbers := make([]uint64, 0, len(numericParts))
	for _, part := range numericParts {
		number, okNumber := canonicalReleaseNumber(part)
		if !okNumber {
			return 0, nil, false
		}
		numbers = append(numbers, number)
	}
	return rank, numbers, true
}
