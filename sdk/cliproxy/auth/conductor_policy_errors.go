package auth

import (
	"errors"
	"strings"
)

// A scheduler forbids the request before any credential executes it. Keep that
// decision separate from an upstream executor's 403, which can permit failover.
type requestPolicyError struct {
	error
	code string
}

func (e requestPolicyError) Unwrap() error       { return e.error }
func (e requestPolicyError) IsRequestStop() bool { return true }

func newRequestPolicyError(err error) error {
	code := "policy_denied"
	var coded interface{ ErrorCode() string }
	if errors.As(err, &coded) && coded != nil {
		if value := strings.TrimSpace(coded.ErrorCode()); value != "" {
			code = value
		}
	}
	return requestPolicyError{error: err, code: code}
}

// RequestPolicyErrorCode reports only policy failures classified at the
// scheduler boundary, never ordinary upstream permission or quota failures.
func RequestPolicyErrorCode(err error) (string, bool) {
	var denied requestPolicyError
	if errors.As(err, &denied) {
		return denied.code, true
	}
	return "", false
}
