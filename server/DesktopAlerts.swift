import AppKit
import UserNotifications
import SQLite3

private let data = Bundle.main.bundleURL.deletingLastPathComponent().appendingPathComponent("data")
private let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

final class Alerts: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    let center = UNUserNotificationCenter.current()
    var db: OpaquePointer?
    var watch: DispatchSourceFileSystemObject?
    var running = false
    var again = false
    var allowed = false

    func applicationWillFinishLaunching(_ notification: Notification) {
        center.delegate = self
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        guard sqlite3_open_v2(data.appendingPathComponent("events.sqlite3").path, &db,
                              SQLITE_OPEN_READWRITE, nil) == SQLITE_OK else { NSApp.terminate(nil); return }
        sqlite3_busy_timeout(db, 5000)
        let fd = open(data.appendingPathComponent("desktop-wake").path, O_EVTONLY)
        guard fd >= 0 else { NSApp.terminate(nil); return }
        let source = DispatchSource.makeFileSystemObjectSource(fileDescriptor: fd, eventMask: [.write,.extend,.attrib], queue: .main)
        source.setEventHandler { self.refresh() }
        source.setCancelHandler { close(fd) }
        watch = source
        source.resume()
        let read = UNNotificationAction(identifier: "read", title: "标为已读", options: [])
        center.setNotificationCategories([UNNotificationCategory(identifier: "alert", actions: [read],
            intentIdentifiers: [], options: [.customDismissAction])])
        center.requestAuthorization(options: [.alert,.sound]) { _,_ in
            DispatchQueue.main.async { self.refresh() }
        }
    }

    func query(_ sql: String, _ values: [String] = []) throws -> [[String]] {
        var statement: OpaquePointer?
        func failure() -> NSError { NSError(domain:"SQLite", code:Int(sqlite3_errcode(db))) }
        guard sqlite3_prepare_v2(db, sql, -1, &statement, nil) == SQLITE_OK else { throw failure() }
        defer { sqlite3_finalize(statement) }
        for (index,value) in values.enumerated() {
            sqlite3_bind_text(statement, Int32(index+1), value, -1, transient)
        }
        var rows: [[String]] = []
        var status = sqlite3_step(statement)
        while status == SQLITE_ROW {
            rows.append((0..<sqlite3_column_count(statement)).map { String(cString: sqlite3_column_text(statement,$0)) })
            status = sqlite3_step(statement)
        }
        guard status == SQLITE_DONE else { throw failure() }
        return rows
    }

    func retry() {
        DispatchQueue.main.asyncAfter(deadline:.now()+5) { self.refresh() }
    }

    func refresh() {
        if running { again = true; return }
        running = true
        center.getNotificationSettings { settings in
            DispatchQueue.main.async {
                self.allowed = [.authorized,.provisional].contains(settings.authorizationStatus)
                try? String(settings.authorizationStatus.rawValue).write(to:data.appendingPathComponent("desktop-permission"),atomically:true,encoding:.utf8)
                self.reconcile()
            }
        }
    }

    func finished() {
        running = false
        if again { again=false; refresh() }
    }

    func reconcile() {
        center.getDeliveredNotifications { notifications in
            DispatchQueue.main.async {
                do {
                    for item in notifications {
                        let id=item.request.identifier
                        if try self.query("SELECT 1 FROM log_item WHERE id=? AND seen=0 AND cleared=0",[id]).isEmpty {
                            self.center.removeDeliveredNotifications(withIdentifiers:[id])
                        }
                    }
                    guard self.allowed, let row = try self.query("""
                        SELECT d.id,d.body FROM desktop_alert d JOIN log_item l USING(id)
                        WHERE d.submitted=0 AND l.seen=0 AND l.cleared=0 ORDER BY l.seq LIMIT 1
                        """).first else { self.finished(); return }
                    let content=UNMutableNotificationContent()
                    let config = try Data(contentsOf: data.appendingPathComponent("device.json"))
                    let device = try JSONSerialization.jsonObject(with: config) as? [String:Any]
                    content.title=(device?["name"] as? String ?? "受控端")+" · 布防"
                    content.body=row[1]
                    content.sound = .default
                    content.categoryIdentifier="alert"
                    self.center.add(UNNotificationRequest(identifier: row[0],content: content,trigger:nil)) { err in
                        DispatchQueue.main.async {
                            if err == nil {
                                do { _ = try self.query("UPDATE desktop_alert SET submitted=1 WHERE id=?",[row[0]])
                                    self.again=true
                                } catch { self.retry() }
                            } else { self.retry() }
                            self.finished()
                        }
                    }
                } catch { self.finished(); self.retry() }
            }
        }
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler completion: @escaping (UNNotificationPresentationOptions)->Void) {
        completion([.banner,.list,.sound])
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                withCompletionHandler completion: @escaping ()->Void) {
        let id=response.notification.request.identifier
        DispatchQueue.main.async {
            do {
                _ = try self.query("UPDATE log_item SET seen=1 WHERE id=? AND seen=0",[id])
                center.removeDeliveredNotifications(withIdentifiers:[id])
                // The database is authoritative even while the web service is restarting.
                if let token = try? String(contentsOf:data.appendingPathComponent("desktop-token"),encoding:.utf8) {
                    var req=URLRequest(url:URL(string:"http://127.0.0.1:18762/desktop-changed")!)
                    req.httpMethod="POST"
                    req.setValue("Bearer "+token,forHTTPHeaderField:"Authorization")
                    URLSession.shared.dataTask(with:req).resume()
                }
            } catch { NSLog("Could not store read status for notification") }
            completion()
        }
    }
}

let delegate=Alerts()
NSApplication.shared.setActivationPolicy(.accessory)
NSApplication.shared.delegate=delegate
NSApplication.shared.run()
