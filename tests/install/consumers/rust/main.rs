use semq::{build_info, Codec, CodecConfig, Encoding, Floor, Ids, Manifest};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    println!("loaded core: {:?}", build_info());
    for (name, config) in [
        ("quant", CodecConfig::quant(4, 4)?),
        ("phase", CodecConfig::phase(4, 8)?),
        ("orbit", CodecConfig::orbit(4, 50)?),
    ] {
        let codec = Codec::new(&config)?;
        for (kind, ids) in [
            ("u64", Ids::u64(&[2, 1])),
            ("utf8", Ids::utf8(&["doc-2", "doc-1"])),
        ] {
            let mut vectors = [1.0_f32, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0];
            let manifest = Manifest::from([("encoder".into(), "artifact".into())]);
            let state = codec.encode(ids, &vectors, Some(&manifest))?;
            let path = format!("{name}-{kind}.semq");
            std::fs::write(&path, state.to_bytes())?;
            let restored = Encoding::from_bytes(&std::fs::read(path)?)?;
            assert_eq!(state, restored);
            assert_eq!(restored.len(), 2);
            let null = restored.diff(&state)?;
            let floor = Floor::measure(&[&null])?;
            assert!(null.within(&Floor::from_report(&floor.as_report())?)?);
            vectors[0] = -1.0;
            let candidate = codec.encode(ids, &vectors, Some(&manifest))?;
            let diff = restored.diff(&candidate)?;
            assert_eq!(diff.changed().len(), 1);
            assert_eq!(Some(diff.changed()[0].0.clone()), ids.get(0));
            assert!(!diff.within(&floor)?);
            println!("{name} {kind} encode/restore/diff/floor OK");
        }
    }
    Ok(())
}
