package responses

import (
	"fmt"
	"testing"

	"github.com/MoeForge/moego/ojson"
)

func TestInputStringRemainsAUserMessage(t *testing.T) {
	for _, stream := range []bool{false, true} {
		out, err := ConvertOpenAIResponsesRequestToClaude("claude-haiku-4-5-20251001", []byte(`{"input":"Reply \"lab-ok\".\nNext line","max_output_tokens":64}`), stream)
		if err != nil {
			t.Fatal(err)
		}
		if ojson.GetBytes(out, "messages.#").Int() != 1 || ojson.GetBytes(out, "messages.0.role").String() != "user" || ojson.GetBytes(out, "messages.0.content").String() != "Reply \"lab-ok\".\nNext line" {
			t.Fatalf("plain input disappeared or changed: %s", out)
		}
		if ojson.GetBytes(out, "max_tokens").Int() != 64 {
			t.Fatalf("output limit lost: %s", out)
		}
	}
}

// Nonempty string input is forwarded verbatim, including surrounding
// whitespace. Empty or whitespace-only input is never forwarded as user text.
func TestInputStringBlankAndPaddedWireBehavior(t *testing.T) {
	for _, stream := range []bool{false, true} {
		out, err := ConvertOpenAIResponsesRequestToClaude("claude-fable-5-1", []byte(`{"input":"  padded\t"}`), stream)
		if err != nil {
			t.Fatal(err)
		}
		if ojson.GetBytes(out, "messages.#").Int() != 1 || ojson.GetBytes(out, "messages.0.content").String() != "  padded\t" {
			t.Fatalf("padded input changed: %s", out)
		}
		for _, input := range []string{`""`, `"   "`, `"\n\t "`} {
			for _, body := range []string{`{"input":%s}`, `{"input":%s,"instructions":"sys"}`} {
				payload := []byte(fmt.Sprintf(body, input))
				out, err := ConvertOpenAIResponsesRequestToClaude("claude-fable-5-1", payload, stream)
				if err != nil {
					t.Fatalf("%s: %v", payload, err)
				}
				messages := ojson.GetBytes(out, "messages")
				if !messages.IsArray() {
					t.Fatalf("%s: messages missing: %s", payload, out)
				}
				for _, message := range messages.Array() {
					if message.Get("role").String() != "user" {
						t.Fatalf("%s: unexpected message role: %s", payload, out)
					}
					if content := message.Get("content"); content.Type == ojson.String {
						t.Fatalf("%s: blank input forwarded as user text: %s", payload, out)
					} else {
						for _, part := range content.Array() {
							if part.Get("text").String() != "" {
								t.Fatalf("%s: blank input forwarded as user text: %s", payload, out)
							}
						}
					}
				}
				if body == `{"input":%s}` && len(messages.Array()) != 0 {
					t.Fatalf("%s: blank input created a message: %s", payload, out)
				}
			}
		}
	}
}

func TestReasoningEffortMapsUnadvertisedClaudeLevels(t *testing.T) {
	for _, stream := range []bool{false, true} {
		out, err := ConvertOpenAIResponsesRequestToClaude("claude-opus-4-6", []byte(`{"input":"hi","reasoning":{"effort":"xhigh"}}`), stream)
		if err != nil {
			t.Fatal(err)
		}
		if got := ojson.GetBytes(out, "output_config.effort").String(); got != "max" {
			t.Fatalf("output_config.effort = %q, want max: %s", got, out)
		}
	}
}
