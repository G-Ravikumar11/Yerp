import Capacitor
import SwiftUI
import UIKit

/// iOS only. The phone app's bottom bar, drawn natively as Liquid Glass and floated over the web view. The web app tells it
/// what to show (showTabBar / select / setBadge / setVisible / hideTabBar) and hears back about taps (tabSelected, actionTapped).
/// With this plugin missing (a browser, Android, an older iPhone build) the web app draws its own bar, so nothing depends on it.
@objc(YerpGlassPlugin)
public class YerpGlassPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "YerpGlassPlugin"
    public let jsName = "YerpGlass"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "showTabBar", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "select", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "setBadge", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "setVisible", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "hideTabBar", returnType: CAPPluginReturnPromise),
    ]

    private let model = GlassTabBarModel()
    private var host: UIHostingController<GlassTabBarHost>?

    /// Room the bar needs above the bottom edge, as the web app's `--tabbar` (it adds the safe area itself).
    private static let fallbackHeight: CGFloat = 70

    @objc func showTabBar(_ call: CAPPluginCall) {
        let items = (call.getArray("tabs") ?? []).compactMap { $0 as? JSObject }.compactMap { o -> GlassTabItem? in
            guard let id = o["id"] as? String, let title = o["title"] as? String, let symbol = o["symbol"] as? String else { return nil }
            return GlassTabItem(id: id, title: title, symbol: symbol, badge: o["badge"] as? String)
        }
        guard !items.isEmpty else { return call.reject("tabs is empty") }
        let selected = call.getString("selected") ?? ""
        let actionTitle = call.getString("actionTitle")
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.model.tabs = items
            self.model.selected = selected
            self.model.actionTitle = actionTitle
            self.model.onSelect = { [weak self] id in self?.notifyListeners("tabSelected", data: ["id": id]) }
            self.model.onAction = { [weak self] in self?.notifyListeners("actionTapped", data: [:]) }
            self.attach()
            call.resolve(["height": Double(self.measuredHeight())])
        }
    }

    @objc func select(_ call: CAPPluginCall) {
        let id = call.getString("id") ?? ""
        DispatchQueue.main.async { [weak self] in
            self?.model.selected = id
            call.resolve()
        }
    }

    @objc func setBadge(_ call: CAPPluginCall) {
        guard let id = call.getString("id") else { return call.reject("id is required") }
        let count = call.getInt("count") ?? 0
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.model.tabs = self.model.tabs.map { tab in
                tab.id == id ? GlassTabItem(id: tab.id, title: tab.title, symbol: tab.symbol, badge: count > 0 ? (count > 9 ? "9+" : String(count)) : nil) : tab
            }
            call.resolve()
        }
    }

    /// Hidden while the web app's own sheet is open, so the sheet is not covered by the bar.
    @objc func setVisible(_ call: CAPPluginCall) {
        let visible = call.getBool("visible") ?? true
        DispatchQueue.main.async { [weak self] in
            guard let view = self?.host?.view else { return call.resolve() }
            UIView.animate(withDuration: 0.2) { view.alpha = visible ? 1 : 0 }
            view.isUserInteractionEnabled = visible
            call.resolve()
        }
    }

    @objc func hideTabBar(_ call: CAPPluginCall) {
        DispatchQueue.main.async { [weak self] in
            self?.detach()
            call.resolve()
        }
    }

    private func attach() {
        guard host == nil, let parent = bridge?.viewController else { return }
        let controller = UIHostingController(rootView: GlassTabBarHost(model: model))
        controller.view.backgroundColor = .clear
        controller.view.isOpaque = false
        controller.view.translatesAutoresizingMaskIntoConstraints = false
        controller.sizingOptions = .intrinsicContentSize
        parent.addChild(controller)
        parent.view.addSubview(controller.view)
        let guide = parent.view.safeAreaLayoutGuide
        NSLayoutConstraint.activate([
            controller.view.leadingAnchor.constraint(equalTo: guide.leadingAnchor),
            controller.view.trailingAnchor.constraint(equalTo: guide.trailingAnchor),
            controller.view.bottomAnchor.constraint(equalTo: guide.bottomAnchor, constant: -4),
        ])
        controller.didMove(toParent: parent)
        host = controller
    }

    private func detach() {
        guard let controller = host else { return }
        controller.willMove(toParent: nil)
        controller.view.removeFromSuperview()
        controller.removeFromParent()
        host = nil
    }

    private func measuredHeight() -> CGFloat {
        guard let view = host?.view else { return Self.fallbackHeight }
        view.superview?.layoutIfNeeded()
        let height = view.intrinsicContentSize.height
        return height > 0 && height.isFinite ? height + 4 : Self.fallbackHeight
    }
}
