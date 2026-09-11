import SwiftUI
import AppKit
import Observation
import Darwin

struct VideoRow: Codable, Identifiable {
    var id: String
    var title: String
    var source: String
    var url: String
    var accessible: Bool
    var status: String
    var error: String?
    var downloads: [String:String]
    var label: String {
        switch status { case "complete": return "Descargado"; case "downloading": return "Descargando"; case "failed": return "Falló"; case "locked": return "Sin acceso"; default: return "Pendiente" }
    }
}
struct Inventory: Codable {
    var target: String
    var scope: String
    var items: [VideoRow]
    var courses: Int
    var lessons: Int
    var posts: Int
    var warnings: [String]
    var complete: Bool
    var scanned_at: String
}

@MainActor @Observable final class Downloader {
    var link = "https://www.skool.com/sellersclub"
    var quality = "best"
    var scope = "all"
    var folder = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Downloads/Skool")
    var busy = false
    var status = "Analiza una comunidad para ver sus videos antes de descargar."
    var progress = 0.0
    var batchProgress = 0.0
    var inventory: Inventory?
    var selected = Set<String>()
    var search = ""
    var source = "Todos"
    var result: URL?
    var action = "scan"
    private var process: Process?
    private var buffer = Data()
    private var cancelled = false
    private let support = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/Skool Downloader")
    var catalogURL: URL { support.appendingPathComponent("catalog.json") }
    var sources: [String] { ["Todos"] + Set(inventory?.items.map(\.source) ?? []).sorted() }
    var visible: [VideoRow] { (inventory?.items ?? []).filter { (source == "Todos" || $0.source == source) && (search.isEmpty || ($0.title + " " + $0.source).localizedCaseInsensitiveContains(search)) } }
    init() {
        if let data = try? Data(contentsOf: catalogURL), let decoded = try? JSONDecoder().decode(Inventory.self, from: data) {
            inventory = decoded; link = decoded.target; scope = decoded.scope
            selected = Set(decoded.items.filter { $0.accessible && $0.status != "complete" }.map(\.id))
            status = "Inventario guardado del \(decoded.scanned_at). Analiza de nuevo para actualizar."
        }
    }
    func start(_ requested: String) {
        guard !busy else { return }
        if requested == "batch", let inventory { link = inventory.target }
        let root = Bundle.main.object(forInfoDictionaryKey: "EngineRoot") as? String ?? ""
        let task = Process()
        task.executableURL = URL(fileURLWithPath: root + "/.venv/bin/python")
        task.arguments = ["-u", root + "/engine.py", link, "--quality", quality, "--output", folder.path, "--action", requested, "--scope", scope, "--catalog", catalogURL.path]
        do {
            try FileManager.default.createDirectory(at: support, withIntermediateDirectories: true)
            if requested == "batch" {
                let selectionURL = support.appendingPathComponent("selection.json")
                try JSONEncoder().encode(Array(selected)).write(to: selectionURL, options: .atomic)
                task.arguments! += ["--selection", selectionURL.path]
            }
        } catch { status = "Error: \(error.localizedDescription)"; return }
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        task.environment = env
        let pipe = Pipe(); task.standardOutput = pipe; task.standardError = pipe
        busy = true; action = requested; progress = 0; batchProgress = 0; result = nil; cancelled = false; buffer = Data()
        if requested == "scan" { inventory = nil; selected = []; source = "Todos" }
        status = "Preparando navegador…"
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil; return }
            Task { @MainActor in self?.consume(data) }
        }
        task.terminationHandler = { [weak self] task in
            Task { @MainActor in
                guard let self else { return }
                self.busy = false; self.process = nil
                if self.cancelled { self.status = "Cancelado. El inventario y los avances guardados permiten continuar." }
                else if task.terminationStatus != 0 && !self.status.hasPrefix("Error:") { self.status = "Error: no se completó la operación. Comprueba tu sesión y vuelve a intentarlo." }
            }
        }
        process = task
        do { try task.run() } catch { busy = false; process = nil; status = "Error: \(error.localizedDescription)" }
    }
    private func consume(_ data: Data) {
        buffer.append(data)
        while let end = buffer.firstIndex(of: 10) {
            let line = Data(buffer.prefix(upTo: end)); buffer.removeSubrange(...end)
            guard let event = try? JSONSerialization.jsonObject(with: line) as? [String: Any], let kind = event["event"] as? String else { continue }
            if let message = event["message"] as? String { status = (kind == "error" ? "Error: " : "") + message }
            if kind == "inventory", let value = event["catalog"], let data = try? JSONSerialization.data(withJSONObject: value), let decoded = try? JSONDecoder().decode(Inventory.self, from: data) {
                let oldIDs = Set(inventory?.items.map(\.id) ?? [])
                inventory = decoded
                selected.formUnion(decoded.items.filter { $0.accessible && !oldIDs.contains($0.id) && $0.status != "complete" }.map(\.id))
            }
            if let pct = event["percent"] as? Double {
                if kind == "batch_progress" { batchProgress = min(max(pct,0),100) }
                else { progress = min(max(pct,0),100) }
            }
            if kind == "item", let id = event["id"] as? String, let state = event["status"] as? String, let index = inventory?.items.firstIndex(where: { $0.id == id }) {
                inventory?.items[index].status = state
                if state == "failed" { inventory?.items[index].error = event["message"] as? String }
                if state == "downloading" { progress = 0 }
            }
            if kind == "batch_done" { batchProgress = 100; progress = 100; result = folder }
            if kind == "done", let path = event["path"] as? String { result = URL(fileURLWithPath: path); progress = 100 }
        }
    }
    func stop() {
        guard let process, process.isRunning else { return }
        cancelled = true; status = "Cancelando…"
        if kill(-process.processIdentifier, SIGTERM) != 0 { process.terminate() }
    }
    func chooseFolder() {
        let panel = NSOpenPanel(); panel.canChooseFiles = false; panel.canChooseDirectories = true
        panel.canCreateDirectories = true; panel.directoryURL = folder
        if panel.runModal() == .OK, let url = panel.url { folder = url }
    }
    func export() {
        let panel = NSSavePanel(); panel.nameFieldStringValue = "inventario-skool.json"
        if panel.runModal() == .OK, let url = panel.url {
            do { try Data(contentsOf: catalogURL).write(to: url, options: .atomic); status = "Inventario exportado." }
            catch { status = "Error: \(error.localizedDescription)" }
        }
    }
}

struct MainView: View {
    @State private var model = Downloader()
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 12) {
                Image(systemName: "arrow.down.circle.fill").font(.system(size: 38)).foregroundStyle(.orange)
                VStack(alignment: .leading) {
                    Text("Skool Downloader").font(.title.bold())
                    Text("Analiza · Selecciona · Descarga").foregroundStyle(.secondary)
                }
                Spacer()
                if model.busy { Button("Cancelar") { model.stop() } }
            }
            HStack {
                TextField("URL de comunidad, curso, lección o publicación", text: $model.link).textFieldStyle(.roundedBorder).disabled(model.busy)
                Button("Analizar") { model.start("scan") }.buttonStyle(.borderedProminent).tint(.orange).disabled(model.busy)
            }
            HStack {
                Picker("Incluir", selection: $model.scope) {
                    Text("Aula + publicaciones").tag("all"); Text("Solo aula").tag("courses"); Text("Solo publicaciones").tag("posts")
                }.frame(width: 270)
                Picker("Calidad máxima", selection: $model.quality) {
                    Text("Mejor disponible").tag("best")
                    ForEach(["2160", "1440", "1080", "720", "480", "360"], id: \.self) { Text($0 + "p").tag($0) }
                }.frame(width: 270)
                Spacer()
                Button("Carpeta…") { model.chooseFolder() }
            }.disabled(model.busy)
            if let inventory = model.inventory {
                HStack(spacing: 24) {
                    count("Videos", inventory.items.count)
                    count("Cursos", inventory.courses)
                    count("Lecciones", inventory.lessons)
                    count("Publicaciones", inventory.posts)
                    Spacer()
                    Text(model.busy && model.action == "scan" ? "Contando…" : (inventory.complete ? "Análisis completo" : "Inventario parcial")).font(.caption).foregroundStyle(inventory.complete ? .green : .orange)
                }
                if !inventory.warnings.isEmpty {
                    DisclosureGroup("\(inventory.warnings.count) avisos de acceso o contenido no analizado") {
                        ScrollView { Text(inventory.warnings.joined(separator: "\n")).font(.caption).frame(maxWidth: .infinity, alignment: .leading).textSelection(.enabled) }.frame(maxHeight: 70)
                    }
                }
                HStack {
                    TextField("Buscar video…", text: $model.search).textFieldStyle(.roundedBorder)
                    Picker("Curso", selection: $model.source) { ForEach(model.sources, id: \.self) { Text($0).tag($0) } }.frame(maxWidth: 370)
                }
                HStack {
                    Button("Seleccionar visibles") { model.selected.formUnion(model.visible.filter(\.accessible).map(\.id)) }
                    Button("Ninguno") { model.selected.removeAll() }
                    Button("Solo fallidos") { model.selected = Set(inventory.items.filter { $0.status == "failed" }.map(\.id)) }
                    Button("Intentar bloqueados") { model.selected.formUnion(inventory.items.filter { !$0.accessible || $0.status == "locked" }.map(\.id)) }.help("Reintenta las lecciones marcadas Sin acceso; útil si eres admin/dueño. Skool decide qué entrega.")
                    Spacer()
                    Text("\(model.selected.count) seleccionados").foregroundStyle(.secondary)
                }.disabled(model.busy)
                List(model.visible) { row in
                    HStack(spacing: 10) {
                        Toggle("Seleccionar \(row.title)", isOn: Binding(get: { model.selected.contains(row.id) }, set: { if $0 { model.selected.insert(row.id) } else { model.selected.remove(row.id) } })).labelsHidden().toggleStyle(.checkbox).disabled(model.busy)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(row.title).lineLimit(1)
                            Text(row.source).font(.caption).foregroundStyle(.secondary)
                            if let error = row.error { Text(error).font(.caption).foregroundStyle(.red).lineLimit(2) }
                        }
                        Spacer()
                        Text(row.label).font(.caption).foregroundStyle(row.status == "failed" ? .red : .secondary)
                        Button { if let url = URL(string: row.url) { NSWorkspace.shared.open(url) } } label: { Image(systemName: "arrow.up.right.square") }.help("Abrir en Skool")
                    }.padding(.vertical, 3)
                }.frame(minHeight: 210, maxHeight: .infinity)
            } else {
                ContentUnavailableView("Descubre todos los videos accesibles", systemImage: "rectangle.stack.badge.play", description: Text("Pega una comunidad para recorrer sus cursos y publicaciones. El conteo aparece antes de descargar. Inicia sesión en el navegador de la app cuando se abra."))
                    .frame(maxHeight: .infinity)
            }
            VStack(alignment: .leading, spacing: 6) {
                if model.busy && model.action == "scan" { ProgressView().controlSize(.small) }
                else { ProgressView(value: model.action == "batch" ? model.batchProgress : model.progress, total: 100) }
                Text(model.status).font(.callout).lineLimit(3).textSelection(.enabled).frame(minHeight: 32, alignment: .topLeading)
            }
            HStack {
                Button("Descargar selección (\(model.selected.count))") { model.start("batch") }.buttonStyle(.borderedProminent).tint(.orange).disabled(model.busy || model.selected.isEmpty)
                Button("Exportar inventario") { model.export() }.disabled(model.busy || model.inventory == nil)
                Spacer()
                Button("Abrir carpeta") { try? FileManager.default.createDirectory(at: model.folder, withIntermediateDirectories: true); NSWorkspace.shared.open(model.folder) }
            }
            Text(model.folder.path + " · Avance guardado · El conteo corresponde al contenido accesible durante el análisis").font(.caption2).foregroundStyle(.secondary)
        }.padding(24).frame(minWidth: 860, idealWidth: 980, minHeight: 690, idealHeight: 780).onDisappear { model.stop() }
    }
    private func count(_ title: String, _ value: Int) -> some View {
        VStack(alignment: .leading, spacing: 1) { Text(value.formatted()).font(.title2.bold()); Text(title).font(.caption).foregroundStyle(.secondary) }
    }
}
@main struct SkoolApp: App {
    var body: some Scene { WindowGroup { MainView() }.defaultSize(width: 980, height: 780) }
}
