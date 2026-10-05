package main

import (
	"fmt"
	"os"

	semq "github.com/The-SEMQ-Group/semq/bindings/go"
)

func check(err error) {
	if err != nil {
		panic(err)
	}
}

func exercise(name, kind string, cfg semq.CodecConfig, ids semq.IDs) {
	codec, err := semq.NewCodec(cfg)
	check(err)
	defer codec.Close()
	vectors := []float32{1, 0, 0, 0, 0, 1, 0, 0}
	manifest := map[string]string{"encoder": "artifact"}
	state, err := codec.Encode(ids, vectors, manifest)
	check(err)
	defer state.Close()
	path := name + "-" + kind + ".semq"
	check(os.WriteFile(path, state.Bytes(), 0600))
	data, err := os.ReadFile(path)
	check(err)
	restored, err := semq.Load(data)
	check(err)
	defer restored.Close()
	if state.StateID() != restored.StateID() || restored.Len() != 2 {
		panic("roundtrip differs")
	}
	null, err := restored.Diff(state)
	check(err)
	defer null.Close()
	floor, err := semq.MeasureFloor([]*semq.Diff{null})
	check(err)
	defer floor.Close()
	back, err := semq.FloorFromReport(floor.Report())
	check(err)
	defer back.Close()
	within, err := null.Within(back)
	check(err)
	if !within {
		panic("null outside floor")
	}
	vectors[0] = -1
	candidate, err := codec.Encode(ids, vectors, manifest)
	check(err)
	defer candidate.Close()
	diff, err := restored.Diff(candidate)
	check(err)
	defer diff.Close()
	within, err = diff.Within(floor)
	check(err)
	if len(diff.Changed()) != 1 || within {
		panic("changed input not detected")
	}
	fmt.Println(name, kind, "encode/restore/diff/floor OK")
}

func main() {
	fmt.Printf("loaded core: %+v\n", semq.Info())
	for _, name := range []string{"quant", "phase", "orbit"} {
		var cfg semq.CodecConfig
		var err error
		switch name {
		case "quant":
			cfg, err = semq.Quant(4, 4)
		case "phase":
			cfg, err = semq.Phase(4, 8)
		case "orbit":
			cfg, err = semq.Orbit(4, 50)
		}
		check(err)
		exercise(name, "u64", cfg, semq.U64IDs(2, 1))
		exercise(name, "utf8", cfg, semq.UTF8IDs("doc-2", "doc-1"))
	}
}
