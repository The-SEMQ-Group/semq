// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

package semq

/*
#include "semq.h"
*/
import "C"

import "runtime/debug"

// modulePath is this package's module, looked up in the build info.
const modulePath = "github.com/The-SEMQ-Group/semq/bindings/go"

// BuildInfo describes the loaded core and this binding. Backend maps each
// operator name to the kernel the core runs for it on this host. BuildID
// identifies a reproducible build recipe; it is not a provenance proof.
type BuildInfo struct {
	SDKVersion  string
	CoreVersion string
	Backend     map[string]string
	BuildID     string
}

// Info queries the linked core.
func Info() BuildInfo {
	return BuildInfo{
		SDKVersion:  sdkVersion(),
		CoreVersion: C.GoString(C.semq_core_version()),
		Backend: map[string]string{
			"orbit": C.GoString(C.semq_backend_name(C.uint32_t(OperatorOrbit))),
			"phase": C.GoString(C.semq_backend_name(C.uint32_t(OperatorPhase))),
			"quant": C.GoString(C.semq_backend_name(C.uint32_t(OperatorQuant))),
		},
		BuildID: C.GoString(C.semq_build_id()),
	}
}

// sdkVersion is the module version recorded in the binary, or "unknown".
func sdkVersion() string {
	bi, ok := debug.ReadBuildInfo()
	if !ok {
		return "unknown"
	}
	for _, d := range bi.Deps {
		if d.Path != modulePath {
			continue
		}
		if d.Replace != nil && d.Replace.Version != "" {
			return d.Replace.Version
		}
		if d.Version != "" {
			return d.Version
		}
	}
	if bi.Main.Path == modulePath && bi.Main.Version != "" {
		return bi.Main.Version
	}
	return "unknown"
}
