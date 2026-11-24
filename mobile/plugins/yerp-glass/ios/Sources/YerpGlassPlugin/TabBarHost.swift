import SwiftUI

/// One tab as the web app describes it.
struct GlassTabItem: Identifiable, Equatable {
    let id: String
    let title: String
    /// An SF Symbol name.
    let symbol: String
    let badge: String?
}

/// What the bar shows. Everything here changes on the main thread only (the plugin hops there first).
final class GlassTabBarModel: ObservableObject {
    @Published var tabs: [GlassTabItem] = []
    /// The open tab's id, or "" on a screen that is not one of the tabs.
    @Published var selected: String = ""
    /// The round button after the tabs (its VoiceOver name), or nil for none.
    @Published var actionTitle: String?

    var onSelect: ((String) -> Void)?
    var onAction: (() -> Void)?

    func choose(_ id: String) {
        selected = id
        onSelect?(id)
    }
}

/// The bar itself: LiquidGlassKit's floating glass capsule with the + button after the tabs.
struct GlassTabBarHost: View {
    @ObservedObject var model: GlassTabBarModel

    var body: some View {
        GlassTabBar(
            selection: Binding(get: { model.selected }, set: { model.choose($0) }),
            action: model.actionTitle.map { title in
                GlassTabBarAction(title, systemImage: "plus") { model.onAction?() }
            }
        ) {
            for tab in model.tabs {
                GlassTab(tab.title, systemImage: tab.symbol, value: tab.id).badge(tab.badge)
            }
        }
        .frame(maxWidth: 460)
        .padding(.horizontal, 12)
    }
}
