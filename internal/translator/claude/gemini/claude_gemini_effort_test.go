package gemini

import (
	"fmt"
	"testing"

	"github.com/MoeForge/moego/ojson"
)

func TestThinkingLevelPreservesAdvertisedClaudeLevels(t *testing.T) {
	tests := []struct{ model, level, want string }{
		{"claude-fable-5-1", "xhigh", "xhigh"},
		{"claude-fable-5-1", "max", "max"},
		{"claude-opus-4-6", "xhigh", "max"},
		{"claude-opus-4-6", "minimal", "low"},
	}
	for _, test := range tests {
		for _, stream := range []bool{false, true} {
			t.Run(fmt.Sprintf("%s/%s/stream=%t", test.model, test.level, stream), func(t *testing.T) {
				input := fmt.Sprintf(`{"generationConfig":{"thinkingConfig":{"thinkingLevel":%q}},"contents":[{"role":"user","parts":[{"text":"hi"}]}]}`, test.level)
				out, err := ConvertGeminiRequestToClaude(test.model, []byte(input), stream)
				if err != nil {
					t.Fatal(err)
				}
				if got := ojson.GetBytes(out, "output_config.effort").String(); got != test.want {
					t.Fatalf("output_config.effort = %q, want %q: %s", got, test.want, out)
				}
				if got := ojson.GetBytes(out, "thinking.type").String(); got != "adaptive" {
					t.Fatalf("thinking.type = %q, want adaptive: %s", got, out)
				}
			})
		}
	}
}
