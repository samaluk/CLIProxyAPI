package chat_completions

import (
	"fmt"
	"testing"

	"github.com/MoeForge/moego/ojson"
)

func TestReasoningEffortPreservesAdvertisedClaudeLevels(t *testing.T) {
	tests := []struct{ model, effort, want string }{
		{"claude-fable-5-1", "xhigh", "xhigh"},
		{"claude-fable-5-1", "max", "max"},
		{"claude-fable-5-1", " XHIGH ", "xhigh"},
		{"claude-opus-4-6", "xhigh", "max"},
		{"claude-opus-4-6", "minimal", "low"},
	}
	for _, test := range tests {
		for _, stream := range []bool{false, true} {
			t.Run(fmt.Sprintf("%s/%s/stream=%t", test.model, test.effort, stream), func(t *testing.T) {
				input := fmt.Sprintf(`{"model":%q,"reasoning_effort":%q,"messages":[{"role":"user","content":"hi"}]}`, test.model, test.effort)
				out, err := ConvertOpenAIRequestToClaude(test.model, []byte(input), stream)
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
