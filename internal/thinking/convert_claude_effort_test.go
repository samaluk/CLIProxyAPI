package thinking

import "testing"

// Translators preserve levels the target model advertises before calling
// MapToClaudeEffort; the helper only maps legacy aliases for other levels.
// Call-site preservation is covered by the Claude translator effort tests.
func TestMapToClaudeEffortMapsLegacyLevels(t *testing.T) {
	tests := []struct {
		name, input string
		supportsMax bool
		want        string
		valid       bool
	}{
		{"legacy xhigh maps to max", "xhigh", true, "max", true},
		{"legacy xhigh maps to high", "xhigh", false, "high", true},
		{"max without max support", "max", false, "high", true},
		{"legacy minimal", "minimal", true, "low", true},
		{"normalized input", " HIGH ", false, "high", true},
		{"empty", "", true, "", false},
		{"invalid", "bogus", true, "", false},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			got, valid := MapToClaudeEffort(test.input, test.supportsMax)
			if got != test.want || valid != test.valid {
				t.Fatalf("got (%q,%v), want (%q,%v)", got, valid, test.want, test.valid)
			}
		})
	}
}
