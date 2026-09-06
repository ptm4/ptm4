fn main() {
    println!("cargo:rerun-if-changed=assets/icon.ico");
    println!("cargo:rerun-if-changed=app.manifest");
    println!("cargo:rerun-if-changed=build.rs");
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows") {
        let mut res = tauri_winres::WindowsResource::new();
        res.set_icon_with_id("assets/icon.ico", "1");
        res.set_manifest_file("app.manifest");
        res.set("ProductName", "PTMonitor 2");
        res.set("FileDescription", "PTMonitor 2 - lightweight system monitor widget");
        res.set("LegalCopyright", "PTMonitor 2");
        res.compile()
            .expect("failed to compile Windows resources (icon + manifest)");
    }
}
