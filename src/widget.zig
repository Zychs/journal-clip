//! The compact widget. One small always-on-top pane: live mic level, a record
//! button that counts clicks, and the next armed alarm.
//!
//! No Python in this process. It captures WinMM straight into memory, writes
//! one temp wav, then hands that wav to journal-clip.exe (which owns whisper,
//! the 7B and the tape) and shreds the wav when that exe is done.

const std = @import("std");
const builtin = @import("builtin");
const record = @import("record.zig");
const shred = @import("shred.zig");
const cfg = @import("cfg.zig");

// ── win32 ────────────────────────────────────────────────────────────────────

const HINSTANCE = *anyopaque;
const HWND = *anyopaque;
const HDC = *anyopaque;
const HBRUSH = *anyopaque;
const HFONT = *anyopaque;
const HGDIOBJ = *anyopaque;
const HBITMAP = *anyopaque;
const HANDLE = *anyopaque;
const HICON = *anyopaque;
const HCURSOR = *anyopaque;
const HMENU = *anyopaque;
const WPARAM = usize;
const LPARAM = isize;
const LRESULT = isize;
const BOOL = i32;
const COLORREF = u32;

const RECT = extern struct { left: i32, top: i32, right: i32, bottom: i32 };
const POINT = extern struct { x: i32, y: i32 };

const MSG = extern struct {
    hwnd: ?HWND,
    message: u32,
    wParam: WPARAM,
    lParam: LPARAM,
    time: u32,
    pt: POINT,
};

const WNDPROC = *const fn (HWND, u32, WPARAM, LPARAM) callconv(.winapi) LRESULT;

const WNDCLASSEXW = extern struct {
    cbSize: u32,
    style: u32,
    lpfnWndProc: WNDPROC,
    cbClsExtra: i32,
    cbWndExtra: i32,
    hInstance: HINSTANCE,
    hIcon: ?HICON,
    hCursor: ?HCURSOR,
    hbrBackground: ?HBRUSH,
    lpszMenuName: ?[*:0]const u16,
    lpszClassName: [*:0]const u16,
    hIconSm: ?HICON,
};

const PAINTSTRUCT = extern struct {
    hdc: ?HDC,
    fErase: BOOL,
    rcPaint: RECT,
    fRestore: BOOL,
    fIncUpdate: BOOL,
    rgbReserved: [32]u8,
};

const STARTUPINFOW = extern struct {
    cb: u32 = @sizeOf(STARTUPINFOW),
    lpReserved: ?[*:0]u16 = null,
    lpDesktop: ?[*:0]u16 = null,
    lpTitle: ?[*:0]u16 = null,
    dwX: u32 = 0,
    dwY: u32 = 0,
    dwXSize: u32 = 0,
    dwYSize: u32 = 0,
    dwXCountChars: u32 = 0,
    dwYCountChars: u32 = 0,
    dwFillAttribute: u32 = 0,
    dwFlags: u32 = 0,
    wShowWindow: u16 = 0,
    cbReserved2: u16 = 0,
    lpReserved2: ?*u8 = null,
    hStdInput: ?HANDLE = null,
    hStdOutput: ?HANDLE = null,
    hStdError: ?HANDLE = null,
};

const PROCESS_INFORMATION = extern struct {
    hProcess: ?HANDLE = null,
    hThread: ?HANDLE = null,
    dwProcessId: u32 = 0,
    dwThreadId: u32 = 0,
};

extern "user32" fn RegisterClassExW(*const WNDCLASSEXW) callconv(.winapi) u16;
extern "user32" fn CreateWindowExW(u32, [*:0]const u16, [*:0]const u16, u32, i32, i32, i32, i32, ?HWND, ?HMENU, ?HINSTANCE, ?*anyopaque) callconv(.winapi) ?HWND;
extern "user32" fn DefWindowProcW(HWND, u32, WPARAM, LPARAM) callconv(.winapi) LRESULT;
extern "user32" fn ShowWindow(HWND, i32) callconv(.winapi) BOOL;
extern "user32" fn UpdateWindow(HWND) callconv(.winapi) BOOL;
extern "user32" fn GetMessageW(*MSG, ?HWND, u32, u32) callconv(.winapi) BOOL;
extern "user32" fn TranslateMessage(*const MSG) callconv(.winapi) BOOL;
extern "user32" fn DispatchMessageW(*const MSG) callconv(.winapi) LRESULT;
extern "user32" fn PostQuitMessage(i32) callconv(.winapi) void;
extern "user32" fn InvalidateRect(?HWND, ?*const RECT, BOOL) callconv(.winapi) BOOL;
extern "user32" fn SetTimer(?HWND, usize, u32, ?*anyopaque) callconv(.winapi) usize;
extern "user32" fn KillTimer(?HWND, usize) callconv(.winapi) BOOL;
extern "user32" fn BeginPaint(HWND, *PAINTSTRUCT) callconv(.winapi) ?HDC;
extern "user32" fn EndPaint(HWND, *const PAINTSTRUCT) callconv(.winapi) BOOL;
extern "user32" fn FillRect(HDC, *const RECT, HBRUSH) callconv(.winapi) i32;
extern "user32" fn DrawTextW(HDC, [*]const u16, i32, *RECT, u32) callconv(.winapi) i32;
extern "user32" fn GetClientRect(HWND, *RECT) callconv(.winapi) BOOL;
extern "user32" fn LoadCursorW(?HINSTANCE, usize) callconv(.winapi) ?HCURSOR;
extern "user32" fn AdjustWindowRectEx(*RECT, u32, BOOL, u32) callconv(.winapi) BOOL;
extern "user32" fn GetSystemMetrics(i32) callconv(.winapi) i32;
<<<<<<< Updated upstream
=======
extern "user32" fn FindWindowW(?[*:0]const u16, ?[*:0]const u16) callconv(.winapi) ?HWND;
extern "user32" fn GetWindowRect(HWND, *RECT) callconv(.winapi) BOOL;
extern "user32" fn SetWindowPos(HWND, ?HWND, i32, i32, i32, i32, u32) callconv(.winapi) BOOL;
>>>>>>> Stashed changes

extern "gdi32" fn CreateSolidBrush(COLORREF) callconv(.winapi) ?HBRUSH;
extern "gdi32" fn DeleteObject(HGDIOBJ) callconv(.winapi) BOOL;
extern "gdi32" fn CreateFontW(i32, i32, i32, i32, i32, u32, u32, u32, u32, u32, u32, u32, u32, [*:0]const u16) callconv(.winapi) ?HFONT;
extern "gdi32" fn SelectObject(HDC, HGDIOBJ) callconv(.winapi) ?HGDIOBJ;
extern "gdi32" fn SetTextColor(HDC, COLORREF) callconv(.winapi) COLORREF;
extern "gdi32" fn SetBkMode(HDC, i32) callconv(.winapi) i32;
extern "gdi32" fn CreateCompatibleDC(?HDC) callconv(.winapi) ?HDC;
extern "gdi32" fn CreateCompatibleBitmap(HDC, i32, i32) callconv(.winapi) ?HBITMAP;
extern "gdi32" fn BitBlt(HDC, i32, i32, i32, i32, HDC, i32, i32, u32) callconv(.winapi) BOOL;
extern "gdi32" fn DeleteDC(HDC) callconv(.winapi) BOOL;

extern "kernel32" fn GetModuleHandleW(?[*:0]const u16) callconv(.winapi) HINSTANCE;
extern "kernel32" fn GetModuleFileNameW(?HINSTANCE, [*]u16, u32) callconv(.winapi) u32;
extern "kernel32" fn CreateProcessW(?[*:0]const u16, ?[*:0]u16, ?*anyopaque, ?*anyopaque, BOOL, u32, ?*anyopaque, ?[*:0]const u16, *STARTUPINFOW, *PROCESS_INFORMATION) callconv(.winapi) BOOL;
extern "kernel32" fn WaitForSingleObject(HANDLE, u32) callconv(.winapi) u32;
extern "kernel32" fn GetExitCodeProcess(HANDLE, *u32) callconv(.winapi) BOOL;
extern "kernel32" fn CloseHandle(HANDLE) callconv(.winapi) BOOL;
extern "kernel32" fn SetEnvironmentVariableW([*:0]const u16, ?[*:0]const u16) callconv(.winapi) BOOL;
extern "kernel32" fn GetSystemTimeAsFileTime(*u64) callconv(.winapi) void;
extern "kernel32" fn GetTickCount64() callconv(.winapi) u64;

const WM_CREATE = 0x0001;
const WM_DESTROY = 0x0002;
const WM_PAINT = 0x000F;
const WM_ERASEBKGND = 0x0014;
const WM_KEYDOWN = 0x0100;
const WM_TIMER = 0x0113;
const WM_LBUTTONDOWN = 0x0201;

const WS_CAPTION = 0x00C00000;
const WS_SYSMENU = 0x00080000;
const WS_MINIMIZEBOX = 0x00020000;
const WS_VISIBLE = 0x10000000;
const WS_EX_TOPMOST = 0x00000008;
const SW_SHOW = 5;
<<<<<<< Updated upstream
=======
const SWP_NOSIZE = 0x0001;
const SWP_SHOWWINDOW = 0x0040;
const HWND_TOPMOST: HWND = @ptrFromInt(@as(usize, @bitCast(@as(isize, -1))));
>>>>>>> Stashed changes

const DT_CENTER = 0x0001;
const DT_VCENTER = 0x0004;
const DT_SINGLELINE = 0x0020;
const DT_NOPREFIX = 0x0800;
const DT_LEFT_LINE = DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX;
const DT_MID_LINE = DT_CENTER | DT_LEFT_LINE;

const SRCCOPY = 0x00CC0020;
const TRANSPARENT = 1;
const WHDR_DONE = 0x00000001;
const CREATE_NO_WINDOW = 0x08000000;
const VK_RETURN = 0x0D;
const VK_SPACE = 0x20;

const TIMER_TICK = 1; // meter + countdown + child poll
const TIMER_CLICK = 2; // the 1–4 click window
const TIMER_ALARM = 3; // re-read the alarm tape

// ── house look (clip_look.py tokens) ─────────────────────────────────────────

fn rgb(r: u32, g: u32, b: u32) COLORREF {
    return r | (g << 8) | (b << 16);
}

const BG = rgb(0x05, 0x05, 0x09);
const PANEL = rgb(0x10, 0x10, 0x18);
const VOID = rgb(0x0a, 0x0a, 0x10);
const LINE = rgb(0x27, 0x27, 0x39);
const INK = rgb(0xe7, 0xe7, 0xf2);
const INK_MUTE = rgb(0x6c, 0x6c, 0x83);
const CYAN = rgb(0x7c, 0xf7, 0xff);
const CYAN_DEEP = rgb(0x28, 0xa2, 0xb2);
const AMBER = rgb(0xe2, 0xa2, 0x4a);

const WIDGET_W = 300;
const WIDGET_H = 132;

const SAMPLE_RATE = 16000;
const CHUNK_BYTES = 3200; // 0.1s of 16 kHz mono 16-bit
const N_BUFS = 4;
const CLICK_WINDOW_MS = 600;
const SECONDS_PER_CLICK = 30;

const State = enum { idle, recording, busy };

const App = struct {
    gpa: std.mem.Allocator,
    io: std.Io,
    hwnd: ?HWND = null,

    font_mast: ?HFONT = null,
    font_btn: ?HFONT = null,
    font_small: ?HFONT = null,

    hwi: ?record.HWAVEIN = null,
    bufs: [N_BUFS][]u8 = .{&.{}} ** N_BUFS,
    hdrs: [N_BUFS]record.WAVEHDR = undefined,
    device: u32 = 0,
    peak: f32 = 0,

    state: State = .idle,
    take: std.ArrayList(u8) = .empty,
    clicks: u8 = 0,
    limit_ms: u64 = 0,
    started_ms: u64 = 0,

    proc: ?HANDLE = null,
    pending_wav: ?[]u8 = null,

    exe: []const u8 = "",
    root: []const u8 = "",
    tmp: []const u8 = "",
    home: []const u8 = "",
<<<<<<< Updated upstream
=======
    out_dir: []const u8 = "",
    dock_file: []const u8 = "",
    docked: bool = false,
    dock_tick: u8 = 0,
>>>>>>> Stashed changes

    status_buf: [128]u8 = undefined,
    status: []const u8 = "ready",
    alarm_buf: [96]u8 = undefined,
    alarm: []const u8 = "",

    fn setStatus(self: *App, comptime fmt: []const u8, args: anytype) void {
        self.status = std.fmt.bufPrint(&self.status_buf, fmt, args) catch "…";
    }

    fn setAlarm(self: *App, comptime fmt: []const u8, args: anytype) void {
        self.alarm = std.fmt.bufPrint(&self.alarm_buf, fmt, args) catch "";
    }
};

var app: App = undefined;

// ── strings ──────────────────────────────────────────────────────────────────

fn wideZ(buf: []u16, s: []const u8) [:0]u16 {
    const room = buf.len - 1;
    const src = if (s.len <= room) s else s[0..room];
    const n = std.unicode.utf8ToUtf16Le(buf[0..room], src) catch 0;
    buf[n] = 0;
    return buf[0..n :0];
}

fn nowStamp() u64 {
    var ft: u64 = 0;
    GetSystemTimeAsFileTime(&ft);
    return ft;
}

fn tickMs() u64 {
    return GetTickCount64();
}

fn fileExists(io: std.Io, path: []const u8) bool {
    const f = std.Io.Dir.openFileAbsolute(io, path, .{ .mode = .read_only }) catch return false;
    f.close(io);
    return true;
}

// ── paint ────────────────────────────────────────────────────────────────────

fn fillRect(dc: HDC, r: RECT, color: COLORREF) void {
    const brush = CreateSolidBrush(color) orelse return;
    defer _ = DeleteObject(brush);
    _ = FillRect(dc, &r, brush);
}

fn frameRect(dc: HDC, r: RECT, color: COLORREF) void {
    fillRect(dc, .{ .left = r.left, .top = r.top, .right = r.right, .bottom = r.top + 1 }, color);
    fillRect(dc, .{ .left = r.left, .top = r.bottom - 1, .right = r.right, .bottom = r.bottom }, color);
    fillRect(dc, .{ .left = r.left, .top = r.top, .right = r.left + 1, .bottom = r.bottom }, color);
    fillRect(dc, .{ .left = r.right - 1, .top = r.top, .right = r.right, .bottom = r.bottom }, color);
}

fn drawText(dc: HDC, r: RECT, s: []const u8, color: COLORREF, font: ?HFONT, flags: u32) void {
    var buf: [192]u16 = undefined;
    const w = wideZ(&buf, s);
    if (font) |f| _ = SelectObject(dc, f);
    _ = SetBkMode(dc, TRANSPARENT);
    _ = SetTextColor(dc, color);
    var rr = r;
    _ = DrawTextW(dc, w.ptr, @intCast(w.len), &rr, flags);
}

fn buttonRect() RECT {
    return .{ .left = 12, .top = 48, .right = WIDGET_W - 12, .bottom = 48 + 36 };
}

<<<<<<< Updated upstream
=======
fn dockHitRect() RECT {
    return .{ .left = WIDGET_W - 118, .top = 8, .right = WIDGET_W - 66, .bottom = 24 };
}

fn inRect(r: RECT, x: i32, y: i32) bool {
    return x >= r.left and x < r.right and y >= r.top and y < r.bottom;
}

>>>>>>> Stashed changes
fn buttonLabel(self: *App, buf: []u8) []const u8 {
    return switch (self.state) {
        .idle => if (self.clicks == 0)
            "record   1–4 clicks"
        else
            std.fmt.bufPrint(buf, "{d} × 30s   →   {d}s", .{ self.clicks, @as(u32, self.clicks) * SECONDS_PER_CLICK }) catch "record",
        .recording => blk: {
            const gone = tickMs() -| self.started_ms;
            const left = if (gone >= self.limit_ms) 0 else (self.limit_ms - gone + 999) / 1000;
            break :blk std.fmt.bufPrint(buf, "stop  ·  {d}s left", .{left}) catch "stop";
        },
        .busy => "whisper working …",
    };
}

fn onPaint(self: *App, hwnd: HWND) void {
    var ps: PAINTSTRUCT = undefined;
    const hdc = BeginPaint(hwnd, &ps) orelse return;
    defer _ = EndPaint(hwnd, &ps);

    var client: RECT = undefined;
    _ = GetClientRect(hwnd, &client);
    const w = client.right;
    const h = client.bottom;

    // Back buffer: the meter repaints 20×/s and must not flicker.
    const mem = CreateCompatibleDC(hdc) orelse return;
    defer _ = DeleteDC(mem);
    const bmp = CreateCompatibleBitmap(hdc, w, h) orelse return;
    defer _ = DeleteObject(bmp);
    const old_bmp = SelectObject(mem, bmp);
    defer {
        if (old_bmp) |ob| _ = SelectObject(mem, ob);
    }

    fillRect(mem, .{ .left = 0, .top = 0, .right = w, .bottom = h }, BG);

    drawText(
        mem,
<<<<<<< Updated upstream
        .{ .left = 12, .top = 8, .right = w - 60, .bottom = 24 },
=======
        .{ .left = 12, .top = 8, .right = w - 120, .bottom = 24 },
>>>>>>> Stashed changes
        "⬡  journal-clip",
        CYAN,
        self.font_mast,
        DT_LEFT_LINE,
    );
<<<<<<< Updated upstream
=======
    drawText(
        mem,
        dockHitRect(),
        if (self.docked) "float" else "dock",
        CYAN,
        self.font_mast,
        DT_MID_LINE,
    );
>>>>>>> Stashed changes
    var dev_buf: [24]u8 = undefined;
    const dev = std.fmt.bufPrint(&dev_buf, "dev {d}", .{self.device}) catch "dev";
    drawText(
        mem,
        .{ .left = w - 62, .top = 8, .right = w - 12, .bottom = 24 },
        dev,
        INK_MUTE,
        self.font_mast,
        DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX | 0x0002,
    );

    // level
    const meter: RECT = .{ .left = 12, .top = 28, .right = w - 12, .bottom = 40 };
    fillRect(mem, meter, VOID);
    frameRect(mem, meter, LINE);
    const span: f32 = @floatFromInt(meter.right - meter.left - 2);
    const lit = meterLit(span, self.peak);
    if (lit > 0) {
        fillRect(
            mem,
            .{ .left = meter.left + 1, .top = meter.top + 1, .right = meter.left + 1 + lit, .bottom = meter.bottom - 1 },
            if (self.state == .recording) CYAN else CYAN_DEEP,
        );
    }

    // button
    var label_buf: [48]u8 = undefined;
    const btn = buttonRect();
    fillRect(mem, btn, PANEL);
    frameRect(mem, btn, switch (self.state) {
        .idle => if (self.clicks == 0) LINE else CYAN,
        .recording => AMBER,
        .busy => LINE,
    });
    drawText(mem, btn, buttonLabel(self, &label_buf), switch (self.state) {
        .idle => CYAN,
        .recording => AMBER,
        .busy => INK_MUTE,
    }, self.font_btn, DT_MID_LINE);

    drawText(
        mem,
        .{ .left = 12, .top = 90, .right = w - 12, .bottom = 106 },
        self.status,
        INK,
        self.font_small,
        DT_LEFT_LINE,
    );
    if (self.alarm.len > 0) {
        drawText(
            mem,
            .{ .left = 12, .top = 106, .right = w - 12, .bottom = 122 },
            self.alarm,
            INK_MUTE,
            self.font_small,
            DT_LEFT_LINE,
        );
    }

    _ = BitBlt(hdc, 0, 0, w, h, mem, 0, 0, SRCCOPY);
}

// ── capture ──────────────────────────────────────────────────────────────────

/// Lit pixels of the level bar. Silence must stay dark, full scale must fill.
fn meterLit(span: f32, peak: f32) i32 {
    return @intFromFloat(span * std.math.clamp(peak, 0.0, 1.0));
}

fn peakOf(bytes: []const u8) f32 {
    const n = bytes.len / 2;
    if (n == 0) return 0;
    var sum: i64 = 0;
    for (0..n) |i| sum += std.mem.readInt(i16, bytes[i * 2 ..][0..2], .little);
    const mean = @divTrunc(sum, @as(i64, @intCast(n)));
    var top: i64 = 0;
    for (0..n) |i| {
        const v = @as(i64, std.mem.readInt(i16, bytes[i * 2 ..][0..2], .little)) - mean;
        top = @max(top, if (v < 0) -v else v);
    }
    return @min(1.0, @as(f32, @floatFromInt(top)) / 32767.0);
}

fn meterOpen(self: *App) void {
    const wfx: record.WAVEFORMATEX = .{
        .wFormatTag = 1,
        .nChannels = 1,
        .nSamplesPerSec = SAMPLE_RATE,
        .nAvgBytesPerSec = SAMPLE_RATE * 2,
        .nBlockAlign = 2,
        .wBitsPerSample = 16,
        .cbSize = 0,
    };
    var handle: ?record.HWAVEIN = null;
    if (record.waveInOpen(&handle, self.device, &wfx, 0, 0, 0) != 0) {
        self.setStatus("mic {d} would not open — level off", .{self.device});
        return;
    }
    const h = handle.?;
    for (&self.bufs) |*b| {
        b.* = self.gpa.alloc(u8, CHUNK_BYTES) catch {
            _ = record.waveInClose(h);
            self.setStatus("out of memory for capture", .{});
            return;
        };
    }
    self.hwi = h;
    for (&self.hdrs, 0..) |*hdr, i| {
        hdr.* = .{
            .lpData = self.bufs[i].ptr,
            .dwBufferLength = CHUNK_BYTES,
            .dwBytesRecorded = 0,
            .dwUser = 0,
            .dwFlags = 0,
            .dwLoops = 0,
            .lpNext = null,
            .reserved = 0,
        };
        _ = record.waveInPrepareHeader(h, hdr, @sizeOf(record.WAVEHDR));
        _ = record.waveInAddBuffer(h, hdr, @sizeOf(record.WAVEHDR));
    }
    _ = record.waveInStart(h);
}

fn meterClose(self: *App) void {
    if (self.hwi) |h| {
        _ = record.waveInStop(h);
        _ = record.waveInReset(h);
        for (&self.hdrs) |*hdr| _ = record.waveInUnprepareHeader(h, hdr, @sizeOf(record.WAVEHDR));
        _ = record.waveInClose(h);
        self.hwi = null;
    }
    for (&self.bufs) |*b| {
        if (b.len > 0) self.gpa.free(b.*);
        b.* = &.{};
    }
}

/// Drain every finished WinMM buffer: level always, tape only while recording.
fn meterPoll(self: *App) void {
    const h = self.hwi orelse return;
    var loudest: f32 = 0;
    for (&self.hdrs) |*hdr| {
        if (hdr.dwFlags & WHDR_DONE == 0) continue;
        const n: usize = @intCast(hdr.dwBytesRecorded);
        const chunk = hdr.lpData[0..n];
        loudest = @max(loudest, peakOf(chunk));
        if (self.state == .recording) self.take.appendSlice(self.gpa, chunk) catch {};
        _ = record.waveInUnprepareHeader(h, hdr, @sizeOf(record.WAVEHDR));
        hdr.dwFlags = 0;
        hdr.dwBytesRecorded = 0;
        _ = record.waveInPrepareHeader(h, hdr, @sizeOf(record.WAVEHDR));
        _ = record.waveInAddBuffer(h, hdr, @sizeOf(record.WAVEHDR));
    }
    self.peak = @max(loudest, self.peak * 0.72);
}

// ── take → journal-clip.exe ──────────────────────────────────────────────────

fn startTake(self: *App, clicks: u8) void {
    self.take.clearRetainingCapacity();
    self.limit_ms = @as(u64, clicks) * SECONDS_PER_CLICK * 1000;
    self.started_ms = tickMs();
    self.state = .recording;
    self.setStatus("capturing · stop sends early", .{});
}

fn writeTakeWav(self: *App, path: []const u8) !void {
    const file = try std.Io.Dir.createFileAbsolute(self.io, path, .{});
    defer file.close(self.io);
    var write_buf: [4096]u8 = undefined;
    var file_writer = file.writer(self.io, &write_buf);
    const writer = &file_writer.interface;
    try record.writeWavHeader(writer, @intCast(self.take.items.len), SAMPLE_RATE, 1, 16);
    try writer.writeAll(self.take.items);
    try file_writer.flush();
}

fn spawnClip(self: *App, wav: []const u8) !HANDLE {
    const cmdline = try std.fmt.allocPrint(self.gpa, "\"{s}\" --file \"{s}\"", .{ self.exe, wav });
    defer self.gpa.free(cmdline);

    var exe_w: [1024]u16 = undefined;
    var cmd_w: [2048]u16 = undefined;
    var cwd_w: [1024]u16 = undefined;
    const exe_z = wideZ(&exe_w, self.exe);
    const cmd_z = wideZ(&cmd_w, cmdline);
    const cwd_z = wideZ(&cwd_w, self.root);

    var si: STARTUPINFOW = .{};
    var pi: PROCESS_INFORMATION = .{};
    const ok = CreateProcessW(
        exe_z.ptr,
        cmd_z.ptr,
        null,
        null,
        0,
        CREATE_NO_WINDOW,
        null,
        cwd_z.ptr,
        &si,
        &pi,
    );
    if (ok == 0) return error.SpawnFailed;
    if (pi.hThread) |t| _ = CloseHandle(t);
    return pi.hProcess orelse error.SpawnFailed;
}

fn finishTake(self: *App) void {
    self.state = .busy;
    self.peak = 0;

    const seconds = @as(f32, @floatFromInt(self.take.items.len)) / (SAMPLE_RATE * 2.0);
    if (seconds < 0.4) {
        self.state = .idle;
        self.setStatus("too short — nothing sent", .{});
        return;
    }

    const wav = std.fmt.allocPrint(self.gpa, "{s}\\sesefus-widget-{d}.wav", .{ self.tmp, nowStamp() }) catch {
        self.state = .idle;
        self.setStatus("out of memory", .{});
        return;
    };
    writeTakeWav(self, wav) catch |err| {
        self.gpa.free(wav);
        self.state = .idle;
        self.setStatus("wav failed: {s}", .{@errorName(err)});
        return;
    };
    const proc = spawnClip(self, wav) catch |err| {
        shred.shredPath(self.io, wav) catch {};
        self.gpa.free(wav);
        self.state = .idle;
        self.setStatus("journal-clip.exe not started: {s}", .{@errorName(err)});
        return;
    };
    self.proc = proc;
    self.pending_wav = wav;
    self.setStatus("{d:.0}s → journal-clip.exe", .{seconds});
}

/// The child owns whisper and the tape; we own the wav. Poll, then shred.
fn pollChild(self: *App) void {
    const h = self.proc orelse return;
    if (WaitForSingleObject(h, 0) != 0) return;
    var code: u32 = 1;
    _ = GetExitCodeProcess(h, &code);
    _ = CloseHandle(h);
    self.proc = null;
    if (self.pending_wav) |wav| {
        shred.shredPath(self.io, wav) catch {};
        self.gpa.free(wav);
        self.pending_wav = null;
    }
    self.state = .idle;
    if (code == 0) {
<<<<<<< Updated upstream
        self.setStatus("kept text · wav shredded", .{});
=======
        if (self.out_dir.len > 0) {
            self.setStatus("kept · {s}", .{self.out_dir});
        } else {
            self.setStatus("kept text · wav shredded", .{});
        }
>>>>>>> Stashed changes
    } else {
        self.setStatus("journal-clip exit {d} · wav shredded", .{code});
    }
}

// ── alarm tape ───────────────────────────────────────────────────────────────

const AlarmRow = struct {
    id: []const u8 = "",
    title: []const u8 = "",
    state: []const u8 = "",
    next_due: []const u8 = "",
};

fn loadAlarm(self: *App) void {
    if (self.home.len == 0) return;
    var arena = std.heap.ArenaAllocator.init(self.gpa);
    defer arena.deinit();
    const a = arena.allocator();

    const path = std.fmt.allocPrint(a, "{s}\\.sesefus\\clip-alarms.jsonl", .{self.home}) catch return;
    const data = cfg.readFileAlloc(a, self.io, path) catch {
        self.setAlarm("no alarm tape", .{});
        return;
    };

    // Tape is append-then-rewrite, so the last line for an id is the live one.
    var rows: std.ArrayList(AlarmRow) = .empty;
    var lines = std.mem.splitScalar(u8, data, '\n');
    while (lines.next()) |raw| {
        const line = std.mem.trim(u8, raw, " \r\t");
        if (line.len == 0 or line[0] != '{') continue;
        const row = std.json.parseFromSliceLeaky(AlarmRow, a, line, .{ .ignore_unknown_fields = true }) catch continue;
        if (row.id.len == 0) continue;
        for (rows.items) |*seen| {
            if (std.mem.eql(u8, seen.id, row.id)) {
                seen.* = row;
                break;
            }
        } else rows.append(a, row) catch continue;
    }

    var best: ?AlarmRow = null;
    for (rows.items) |row| {
        if (!std.mem.eql(u8, row.state, "armed") or row.next_due.len < 16) continue;
        if (best == null or std.mem.lessThan(u8, row.next_due, best.?.next_due)) best = row;
    }

    if (best) |row| {
        // next_due is ISO: 2026-08-29T08:30:00 → the clock is what fits here.
        const clock = row.next_due[11..16];
        const title = if (row.title.len > 22) row.title[0..22] else row.title;
        self.setAlarm("next  {s}  {s}", .{ clock, title });
    } else {
        self.setAlarm("no alarm armed", .{});
    }
}

// ── window ───────────────────────────────────────────────────────────────────

<<<<<<< Updated upstream
=======
fn followCard(self: *App) void {
    const hwnd = self.hwnd orelse return;
    const title = std.unicode.utf8ToUtf16LeStringLiteral("journal-clip");
    const card = FindWindowW(null, title) orelse return;
    var r: RECT = undefined;
    if (GetWindowRect(card, &r) == 0) return;
    const pos = cfg.dockPos(r.left, r.top, r.bottom - r.top);
    _ = SetWindowPos(hwnd, HWND_TOPMOST, pos.x, pos.y, 0, 0, SWP_NOSIZE | SWP_SHOWWINDOW);
}

fn toggleDock(self: *App) void {
    self.docked = !self.docked;
    if (self.dock_file.len > 0) cfg.writeDockFile(self.io, self.dock_file, self.docked);
    if (self.docked) followCard(self);
}

>>>>>>> Stashed changes
fn onClick(self: *App) void {
    switch (self.state) {
        .idle => {
            self.clicks = @min(self.clicks + 1, 4);
            _ = KillTimer(self.hwnd, TIMER_CLICK);
            _ = SetTimer(self.hwnd, TIMER_CLICK, CLICK_WINDOW_MS, null);
        },
        .recording => finishTake(self),
        .busy => {},
    }
}

fn wndProc(hwnd: HWND, msg: u32, wparam: WPARAM, lparam: LPARAM) callconv(.winapi) LRESULT {
    const self = &app;
    switch (msg) {
        WM_CREATE => {
            self.hwnd = hwnd;
            const consolas = std.unicode.utf8ToUtf16LeStringLiteral("Consolas");
            self.font_mast = CreateFontW(-11, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, consolas);
            self.font_btn = CreateFontW(-15, 0, 0, 0, 700, 0, 0, 0, 1, 0, 0, 5, 0, consolas);
            self.font_small = CreateFontW(-11, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, consolas);
            _ = SetTimer(hwnd, TIMER_TICK, 50, null);
            _ = SetTimer(hwnd, TIMER_ALARM, 30_000, null);
            meterOpen(self);
            loadAlarm(self);
            return 0;
        },
        WM_ERASEBKGND => return 1, // WM_PAINT covers every pixel
        WM_PAINT => {
            onPaint(self, hwnd);
            return 0;
        },
        WM_TIMER => {
            switch (wparam) {
                TIMER_TICK => {
                    meterPoll(self);
                    if (self.state == .recording and tickMs() -| self.started_ms >= self.limit_ms) finishTake(self);
                    pollChild(self);
<<<<<<< Updated upstream
=======
                    self.dock_tick +%= 1;
                    if (self.dock_tick % 8 == 0 and self.dock_file.len > 0) {
                        self.docked = cfg.loadDockedFromPath(self.gpa, self.io, self.dock_file);
                    }
                    if (self.docked) followCard(self);
>>>>>>> Stashed changes
                    _ = InvalidateRect(hwnd, null, 0);
                },
                TIMER_CLICK => {
                    _ = KillTimer(hwnd, TIMER_CLICK);
                    const clicks = self.clicks;
                    self.clicks = 0;
                    if (clicks > 0 and self.state == .idle) startTake(self, clicks);
                },
                TIMER_ALARM => loadAlarm(self),
                else => {},
            }
            return 0;
        },
        WM_LBUTTONDOWN => {
            const x: i32 = @as(i16, @truncate(lparam & 0xffff));
            const y: i32 = @as(i16, @truncate((lparam >> 16) & 0xffff));
<<<<<<< Updated upstream
            const btn = buttonRect();
            if (x >= btn.left and x < btn.right and y >= btn.top and y < btn.bottom) onClick(self);
=======
            if (inRect(dockHitRect(), x, y)) {
                toggleDock(self);
                return 0;
            }
            if (inRect(buttonRect(), x, y)) onClick(self);
>>>>>>> Stashed changes
            return 0;
        },
        WM_KEYDOWN => {
            if (wparam == VK_SPACE or wparam == VK_RETURN) onClick(self);
            return 0;
        },
        WM_DESTROY => {
            _ = KillTimer(hwnd, TIMER_TICK);
            _ = KillTimer(hwnd, TIMER_ALARM);
            meterClose(self);
            if (self.font_mast) |f| _ = DeleteObject(f);
            if (self.font_btn) |f| _ = DeleteObject(f);
            if (self.font_small) |f| _ = DeleteObject(f);
            PostQuitMessage(0);
            return 0;
        },
        else => {},
    }
    return DefWindowProcW(hwnd, msg, wparam, lparam);
}

// ── paths ────────────────────────────────────────────────────────────────────

fn exeDirAlloc(gpa: std.mem.Allocator) ![]u8 {
    var buf: [1024]u16 = undefined;
    const n = GetModuleFileNameW(null, &buf, buf.len);
    if (n == 0) return error.NoModulePath;
    const full = try std.unicode.utf16LeToUtf8Alloc(gpa, buf[0..n]);
    defer gpa.free(full);
    const dir = std.fs.path.dirname(full) orelse ".";
    return gpa.dupe(u8, dir);
}

/// Hand the child what Clip.bat would have handed it, when those files are here.
fn exportChildEnv(self: *App) void {
    var key_w: [64]u16 = undefined;
    var val_w: [1024]u16 = undefined;
    const pairs = [_][2][]const u8{
        .{ "SESEFUS_CLIP_HEAVY", "python\\clip_heavy.py" },
        .{ "SESEFUS_CLIP_CONFIG_PY", "python\\clip_config.py" },
        .{ "SESEFUS_CLIP_ALARM_PY", "python\\clip_alarm.py" },
    };
    for (pairs) |pair| {
        const path = std.fs.path.join(self.gpa, &.{ self.root, pair[1] }) catch continue;
        defer self.gpa.free(path);
        if (!fileExists(self.io, path)) continue;
        _ = SetEnvironmentVariableW(wideZ(&key_w, pair[0]).ptr, wideZ(&val_w, path).ptr);
    }
    const venvs = [_][]const u8{
        "..\\..\\venv\\Scripts\\python.exe",
        "..\\venv\\Scripts\\python.exe",
        "venv\\Scripts\\python.exe",
    };
    for (venvs) |rel| {
        const path = std.fs.path.resolve(self.gpa, &.{ self.root, rel }) catch continue;
        defer self.gpa.free(path);
        if (!fileExists(self.io, path)) continue;
        _ = SetEnvironmentVariableW(wideZ(&key_w, "SESEFUS_CLIP_PYTHON").ptr, wideZ(&val_w, path).ptr);
        break;
    }
}

pub fn main(init: std.process.Init) !void {
    if (builtin.os.tag != .windows) {
        std.debug.print("[clip] the widget is Win32 only\n", .{});
        return;
    }
    const gpa = init.gpa;
    const io = init.io;
    const env = init.environ_map;

    app = .{ .gpa = gpa, .io = io };
    defer app.take.deinit(gpa);

    const bin_dir = try exeDirAlloc(gpa);
    defer gpa.free(bin_dir);
    // zig-out\bin\journal-clip-widget.exe → app root is two levels up.
    const zig_out = std.fs.path.dirname(bin_dir) orelse bin_dir;
    app.root = std.fs.path.dirname(zig_out) orelse zig_out;
    app.exe = try std.fmt.allocPrint(gpa, "{s}\\journal-clip.exe", .{bin_dir});
    defer gpa.free(app.exe);
    app.tmp = env.get("TEMP") orelse env.get("TMP") orelse "C:\\Windows\\Temp";
    app.home = env.get("USERPROFILE") orelse "";
    app.device = cfg.loadInputIndex(gpa, io, env);
<<<<<<< Updated upstream
    app.setStatus("ready", .{});
=======
    if (cfg.dockPath(gpa, env)) |p| app.dock_file = p;
    app.docked = cfg.loadDockedFromPath(gpa, io, app.dock_file);
    if (cfg.loadOutDir(gpa, io, env)) |d| {
        app.out_dir = d;
        app.setStatus("ready · {s}", .{d});
    } else {
        app.setStatus("ready", .{});
    }
>>>>>>> Stashed changes
    exportChildEnv(&app);
    if (!fileExists(io, app.exe)) app.setStatus("journal-clip.exe missing — run zig build", .{});

    const hinst = GetModuleHandleW(null);
    const class_name = std.unicode.utf8ToUtf16LeStringLiteral("JournalClipWidget");
<<<<<<< Updated upstream
    const title = std.unicode.utf8ToUtf16LeStringLiteral("journal-clip");
=======
    const title = std.unicode.utf8ToUtf16LeStringLiteral("journal-clip widget");
>>>>>>> Stashed changes
    const bg = CreateSolidBrush(BG);
    const wc: WNDCLASSEXW = .{
        .cbSize = @sizeOf(WNDCLASSEXW),
        .style = 0x0003, // CS_HREDRAW | CS_VREDRAW
        .lpfnWndProc = &wndProc,
        .cbClsExtra = 0,
        .cbWndExtra = 0,
        .hInstance = hinst,
        .hIcon = null,
        .hCursor = LoadCursorW(null, 32512), // IDC_ARROW
        .hbrBackground = bg,
        .lpszMenuName = null,
        .lpszClassName = class_name,
        .hIconSm = null,
    };
    if (RegisterClassExW(&wc) == 0) return error.RegisterClassFailed;

    const style: u32 = WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX | WS_VISIBLE;
    var want: RECT = .{ .left = 0, .top = 0, .right = WIDGET_W, .bottom = WIDGET_H };
    _ = AdjustWindowRectEx(&want, style, 0, WS_EX_TOPMOST);
    const frame_w = want.right - want.left;
    const frame_h = want.bottom - want.top;
    const x = GetSystemMetrics(0) - frame_w - 32; // bottom-right, clear of the tray
    const y = GetSystemMetrics(1) - frame_h - 96;

    const hwnd = CreateWindowExW(
        WS_EX_TOPMOST,
        class_name,
        title,
        style,
        x,
        y,
        frame_w,
        frame_h,
        null,
        null,
        hinst,
        null,
    ) orelse return error.CreateWindowFailed;
    _ = ShowWindow(hwnd, SW_SHOW);
    _ = UpdateWindow(hwnd);

    var msg: MSG = undefined;
    while (GetMessageW(&msg, null, 0, 0) > 0) {
        _ = TranslateMessage(&msg);
        _ = DispatchMessageW(&msg);
    }

    if (app.proc) |h| _ = CloseHandle(h);
    if (app.pending_wav) |wav| {
        shred.shredPath(io, wav) catch {};
        gpa.free(wav);
    }
<<<<<<< Updated upstream
=======
    if (app.dock_file.len > 0) gpa.free(app.dock_file);
    if (app.out_dir.len > 0) gpa.free(app.out_dir);
>>>>>>> Stashed changes
}

// ── tests ────────────────────────────────────────────────────────────────────

fn pcm(samples: []const i16, buf: []u8) []u8 {
    for (samples, 0..) |s, i| std.mem.writeInt(i16, buf[i * 2 ..][0..2], s, .little);
    return buf[0 .. samples.len * 2];
}

test "peak is amplitude, not dc offset" {
    var buf: [64]u8 = undefined;
    try std.testing.expectEqual(@as(f32, 0), peakOf(pcm(&.{}, &buf)));

    // A hard negative bias with no swing is not level.
    const biased = [_]i16{-8000} ** 8;
    try std.testing.expect(peakOf(pcm(&biased, &buf)) < 0.01);

    // Same bias, real swing: the swing is what shows.
    const ac = [_]i16{ -8000 + 12000, -8000 - 12000 } ** 4;
    try std.testing.expectApproxEqAbs(@as(f32, 12000.0 / 32767.0), peakOf(pcm(&ac, &buf)), 0.01);
}

test "meter bar is dark on silence and full on clip" {
    try std.testing.expectEqual(@as(i32, 0), meterLit(276, 0));
    try std.testing.expectEqual(@as(i32, 0), meterLit(276, 1.0 / 32767.0)); // 1 LSB of room noise
    try std.testing.expectEqual(@as(i32, 138), meterLit(276, 0.5));
    try std.testing.expectEqual(@as(i32, 276), meterLit(276, 1.0));
    try std.testing.expectEqual(@as(i32, 276), meterLit(276, 9.0)); // clamped, never overdraws
}
<<<<<<< Updated upstream
=======

test "dock sits under the card" {
    const pos = cfg.dockPos(40, 80, 680);
    try std.testing.expectEqual(@as(i32, 40), pos.x);
    try std.testing.expectEqual(@as(i32, 760), pos.y);
}
>>>>>>> Stashed changes
