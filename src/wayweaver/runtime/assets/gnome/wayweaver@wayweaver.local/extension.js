import Gio from 'gi://Gio';
import Meta from 'gi://Meta';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const INTERFACE = `
<node>
  <interface name="org.wayweaver.Gnome1">
    <method name="Ping"><arg type="s" direction="out"/></method>
    <method name="ListWindows"><arg type="s" direction="out"/></method>
    <method name="WindowAction">
      <arg type="s" direction="in" name="id"/>
      <arg type="s" direction="in" name="action"/>
      <arg type="s" direction="in" name="params"/>
      <arg type="s" direction="out"/>
    </method>
    <method name="ListWorkspaces"><arg type="s" direction="out"/></method>
    <method name="SwitchWorkspace">
      <arg type="s" direction="in" name="workspace"/>
      <arg type="s" direction="out"/>
    </method>
  </interface>
</node>`;

function response(value) {
    return JSON.stringify(value);
}

function windows() {
    return global.get_window_actors()
        .map(actor => actor.meta_window)
        .filter(window => window && !window.skip_taskbar);
}

function identifier(window) {
    return String(window.get_stable_sequence());
}

function describe(window) {
    const rectangle = window.get_frame_rect();
    const workspace = window.get_workspace();
    return {
        id: identifier(window),
        title: window.get_title() ?? '',
        class: window.get_wm_class() ?? window.get_gtk_application_id() ?? '',
        pid: window.get_pid(),
        desktop: workspace ? workspace.index() : -1,
        x: rectangle.x,
        y: rectangle.y,
        width: rectangle.width,
        height: rectangle.height,
        active: global.display.focus_window === window,
        minimized: window.minimized,
        fullscreen: window.is_fullscreen(),
        maximized: window.get_maximize_flags() === Meta.MaximizeFlags.BOTH,
    };
}

class Bridge {
    constructor(workspaceSettings) {
        this._workspaceSettings = workspaceSettings;
    }

    _workspaceName(index) {
        const configured = this._workspaceSettings.get_strv('workspace-names');
        return configured[index] || `Workspace ${index + 1}`;
    }

    Ping() {
        return response({ok: true});
    }

    ListWindows() {
        return response({windows: windows().map(describe)});
    }

    WindowAction(id, action, encodedParams) {
        const window = windows().find(candidate => identifier(candidate) === id);
        if (!window)
            throw new Error(`window not found: ${id}`);
        const params = encodedParams ? JSON.parse(encodedParams) : {};
        const timestamp = global.get_current_time();
        switch (action) {
        case 'focus_window':
            window.activate(timestamp);
            break;
        case 'close_window':
            window.delete(timestamp);
            break;
        case 'move_window':
            window.move_frame(true, Number(params.x), Number(params.y));
            break;
        case 'resize_window': {
            const rectangle = window.get_frame_rect();
            window.move_resize_frame(
                true,
                rectangle.x,
                rectangle.y,
                Number(params.width),
                Number(params.height));
            break;
        }
        case 'minimize_window':
            window.minimize();
            break;
        case 'maximize_window':
            window.maximize(Meta.MaximizeFlags.BOTH);
            break;
        case 'fullscreen_window':
            if (params.enabled ?? true)
                window.make_fullscreen();
            else
                window.unmake_fullscreen();
            break;
        case 'restore_window':
            if (window.minimized)
                window.unminimize();
            if (window.is_fullscreen())
                window.unmake_fullscreen();
            window.unmaximize(Meta.MaximizeFlags.BOTH);
            break;
        case 'wait_window':
        case 'assert_window':
            break;
        default:
            throw new Error(`unsupported window action: ${action}`);
        }
        return response({window: describe(window)});
    }

    ListWorkspaces() {
        const manager = global.workspace_manager;
        const active = manager.get_active_workspace_index();
        const workspaces = [];
        for (let index = 0; index < manager.get_n_workspaces(); index++) {
            const workspace = manager.get_workspace_by_index(index);
            workspaces.push({
                index,
                name: this._workspaceName(index),
                active: index === active,
            });
        }
        return response({workspaces});
    }

    SwitchWorkspace(value) {
        const manager = global.workspace_manager;
        let index = Number(value);
        if (!Number.isInteger(index)) {
            index = -1;
            for (let candidate = 0; candidate < manager.get_n_workspaces(); candidate++) {
                if (this._workspaceName(candidate) === value) {
                    index = candidate;
                    break;
                }
            }
        }
        if (index < 0 || index >= manager.get_n_workspaces())
            throw new Error(`workspace not found: ${value}`);
        manager.get_workspace_by_index(index).activate(global.get_current_time());
        return response({index});
    }
}

export default class WayweaverExtension extends Extension {
    enable() {
        this._workspaceSettings = new Gio.Settings({
            schema_id: 'org.gnome.desktop.wm.preferences',
        });
        this._bridge = Gio.DBusExportedObject.wrapJSObject(
            INTERFACE,
            new Bridge(this._workspaceSettings));
        this._ownerId = Gio.bus_own_name(
            Gio.BusType.SESSION,
            'org.wayweaver.Gnome',
            Gio.BusNameOwnerFlags.NONE,
            connection => this._bridge.export(connection, '/org/wayweaver/Gnome'),
            null,
            null);
    }

    disable() {
        this._bridge?.unexport();
        this._bridge = null;
        this._workspaceSettings = null;
        if (this._ownerId)
            Gio.bus_unown_name(this._ownerId);
        this._ownerId = 0;
    }
}
