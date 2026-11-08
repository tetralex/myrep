fn main() {
    let dir = std::env::var("CARGO_MANIFEST_DIR").unwrap();
    // Unser eigenes Linker-Skript verwenden
    println!("cargo:rustc-link-arg=-T{dir}/linker.ld");
    println!("cargo:rerun-if-changed=linker.ld");
}
