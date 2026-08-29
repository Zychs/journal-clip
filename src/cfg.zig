//! One home for %USERPROFILE%\.sesefus\clip-config.json reads.
//! The exe and the widget both need the capture device. Neither owns it.

const std = @import("std");

pub const FileCfg = struct {
    out_dir: ?[]const u8 = null,
    input_index: ?i64 = null,
};

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
