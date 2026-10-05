// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

package semq

import (
	"runtime"
	"sync/atomic"
	"unsafe"
)

// A value copy of a public wrapper retains the same owner. Only this object
// owns the native allocation and finalizer. Close may run more than once,
// but must not race with an operation borrowing its handle.
type nativeOwner struct {
	ptr  unsafe.Pointer
	free func(unsafe.Pointer)
}

func newOwner(ptr unsafe.Pointer, free func(unsafe.Pointer)) *nativeOwner {
	owner := &nativeOwner{ptr: ptr, free: free}
	runtime.SetFinalizer(owner, (*nativeOwner).close)
	return owner
}

func (o *nativeOwner) close() {
	if o == nil {
		return
	}
	if p := atomic.SwapPointer(&o.ptr, nil); p != nil {
		o.free(p)
		runtime.SetFinalizer(o, nil)
	}
}

func (o *nativeOwner) pointer() unsafe.Pointer {
	if o == nil {
		return nil
	}
	return atomic.LoadPointer(&o.ptr)
}
