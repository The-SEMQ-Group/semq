package semq

import (
	"errors"
	"math"
	"testing"
)

func TestABICollectionCountBoundaries(t *testing.T) {
	for _, n := range []uint64{0, math.MaxUint32} {
		got, err := abiCount(n)
		if err != nil || uint64(got) != n {
			t.Fatalf("count %d: %d, %v", n, got, err)
		}
	}
	for _, n := range []uint64{uint64(math.MaxUint32) + 1, math.MaxUint64} {
		_, err := abiCount(n)
		var invalid *InvalidInputError
		if !errors.As(err, &invalid) {
			t.Fatalf("count %d narrowed: %v", n, err)
		}
	}
	max := int(^uint(0) >> 1)
	if n, err := sumSize(max-1, 1); err != nil || n != max {
		t.Fatal(n, err)
	}
	if _, err := sumSize(max, 1); err == nil {
		t.Fatal("host size overflow admitted")
	}
}
