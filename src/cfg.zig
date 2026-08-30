//! One home for %USERPROFILE%\.sesefus\clip-config.json reads.
//! The exe and the widget both need the capture device. Neither owns it.

const std = @import("std");
<<<<<<< Updated upstream
=======
const builtin = @import("builtin");

extern "kernel32" fn GetModuleFileNameW(?*anyopaque, [*]u16, u32) callconv(.winapi) u32;
>>>>>>> Stashed changes

pub const FileCfg = struct {
    out_dir: ?[]const u8 = null,
    input_index: ?i64 = null,
};

<<<<<<< Updated upstream
=======
const DockFile = struct {
    docked: bool = false,
};

>>>>>>> Stashed changes
pub fn readFileAlloc(allocator: std.mem.Allocator, io: std.Io, path: []const u8) ![]u8 {
    const file = if (std.fs.path.isAbsolute(path))
        try std.Io.Dir.openFileAbsolute(io, path, .{ .mode = .read_only })
    else
        try std.Io.Dir.cwd().openFile(io, path, .{ .mode = .read_only });
    defer file.close(io);
    var read_buf: [4096]u8 = undefined;
    var reader = file.reader(io, &read_buf);
    return try reader.interface.allocRemaining(allocator, .unlimited);
}

/// Caller frees. Null when there is no USERPROFILE to hang it on.
pub fn configPath(allocator: std.mem.Allocator, env: anytype) ?[]u8 {
    if (env.get("SESEFUS_CLIP_CONFIG")) |p| return allocator.dupe(u8, p) catch null;
    const home = env.get("USERPROFILE") orelse return null;
    return std.fmt.allocPrint(allocator, "{s}\\.sesefus\\clip-config.json", .{home}) catch null;
}

/// change-input's device. 0 when the file is missing, torn, or unset.
pub fn loadInputIndex(allocator: std.mem.Allocator, io: std.Io, env: anytype) u32 {
    const path = configPath(allocator, env) orelse return 0;
    defer allocator.free(path);
    const data = readFileAlloc(allocator, io, path) catch return 0;
    defer allocator.free(data);
    const parsed = std.json.parseFromSlice(FileCfg, allocator, data, .{ .ignore_unknown_fields = true }) catch return 0;
    defer parsed.deinit();
    if (parsed.value.input_index) |i| {
        if (i >= 0) return @intCast(i);
    }
    return 0;
}
<<<<<<< Updated upstream
=======

/// Caller frees. Null when unset.
pub fn loadOutDir(allocator: std.mem.Allocator, io: std.Io, env: anytype) ?[]u8 {
    const path = configPath(allocator, env) orelse return null;
    defer allocator.free(path);
    const data = readFileAlloc(allocator, io, path) catch return null;
    defer allocator.free(data);
    const parsed = std.json.parseFromSlice(FileCfg, allocator, data, .{ .ignore_unknown_fields = true }) catch return null;
    defer parsed.deinit();
    const raw = parsed.value.out_dir orelse return null;
    if (raw.len == 0) return null;
    return allocator.dupe(u8, raw) catch null;
}

pub fn dockPath(allocator: std.mem.Allocator, env: anytype) ?[]u8 {
    if (env.get("SESEFUS_CLIP_DOCK")) |p| return allocator.dupe(u8, p) catch null;
    const home = env.get("USERPROFILE") orelse return null;
    return std.fmt.allocPrint(allocator, "{s}\\.sesefus\\clip-dock.json", .{home}) catch null;
}

pub fn loadDocked(allocator: std.mem.Allocator, io: std.Io, env: anytype) bool {
    const path = dockPath(allocator, env) orelse return false;
    defer allocator.free(path);
    return loadDockedFromPath(allocator, io, path);
}

pub fn writeDockFile(io: std.Io, path: []const u8, docked: bool) void {
    if (path.len == 0) return;
    if (std.fs.path.dirname(path)) |dir| {
        if (std.fs.path.isAbsolute(dir)) {
            std.Io.Dir.cwd().createDirPath(io, dir) catch {};
        }
    }
    const body = if (docked) "{\"docked\":true}\n" else "{\"docked\":false}\n";
    const file = if (std.fs.path.isAbsolute(path))
        std.Io.Dir.createFileAbsolute(io, path, .{ .truncate = true }) catch return
    else
        std.Io.Dir.cwd().createFile(io, path, .{}) catch return;
    defer file.close(io);
    file.writeStreamingAll(io, body) catch {};
}

pub fn saveDocked(allocator: std.mem.Allocator, io: std.Io, env: anytype, docked: bool) void {
    const path = dockPath(allocator, env) orelse return;
    defer allocator.free(path);
    writeDockFile(io, path, docked);
}

pub fn loadDockedFromPath(allocator: std.mem.Allocator, io: std.Io, path: []const u8) bool {
    if (path.len == 0) return false;
    const data = readFileAlloc(allocator, io, path) catch return false;
    defer allocator.free(data);
    const parsed = std.json.parseFromSlice(DockFile, allocator, data, .{ .ignore_unknown_fields = true }) catch return false;
    defer parsed.deinit();
    return parsed.value.docked;
}

/// Widget sits flush under the card. Same left edge.
pub fn dockPos(card_x: i32, card_y: i32, card_h: i32) struct { x: i32, y: i32 } {
    return .{ .x = card_x, .y = card_y + card_h };
}

/// Directory of this process's exe. Caller frees.
pub fn exeDirAlloc(gpa: std.mem.Allocator) ![]u8 {
    if (builtin.os.tag != .windows) return error.NotWindows;
    var buf: [1024]u16 = undefined;
    const n = GetModuleFileNameW(null, &buf, buf.len);
    if (n == 0) return error.NoModulePath;
    const full = try std.unicode.utf16LeToUtf8Alloc(gpa, buf[0..n]);
    defer gpa.free(full);
    const dir = std.fs.path.dirname(full) orelse ".";
    return gpa.dupe(u8, dir);
}

/// App root: two levels up from zig-out\bin. Caller frees.
pub fn clipRootAlloc(gpa: std.mem.Allocator) ![]u8 {
    const bin_dir = try exeDirAlloc(gpa);
    defer gpa.free(bin_dir);
    const zig_out = std.fs.path.dirname(bin_dir) orelse bin_dir;
    const root = std.fs.path.dirname(zig_out) orelse zig_out;
    return gpa.dupe(u8, root);
}

pub fn fileExists(io: std.Io, path: []const u8) bool {
    const f = if (std.fs.path.isAbsolute(path))
        std.Io.Dir.openFileAbsolute(io, path, .{ .mode = .read_only }) catch return false
    else
        std.Io.Dir.cwd().openFile(io, path, .{ .mode = .read_only }) catch return false;
    f.close(io);
    return true;
}
>>>>>>> Stashed changes
