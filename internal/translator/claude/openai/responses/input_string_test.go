package responses

import (
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
