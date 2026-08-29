//! Overwrite then unlink. Not the Recycle Bin. Zig 0.16 Io.

const std = @import("std");

pub fn shredPath(io: std.Io, path: []const u8) !void {
    {
        const file = if (std.fs.path.isAbsolute(path))
            try std.Io.Dir.openFileAbsolute(io, path, .{ .mode = .read_write })
        else
            try std.Io.Dir.cwd().openFile(io, path, .{ .mode = .read_write });
        defer file.close(io);

        const size = try file.length(io);
        var buf: [4096]u8 = undefined;
        var pass: u8 = 0;
        while (pass < 2) : (pass += 1) {
            var offset: u64 = 0;
            while (offset < size) {
                const n: usize = @intCast(@min(size - offset, buf.len));
                if (pass == 0) {
                    var prng = std.Random.DefaultPrng.init(size ^ offset ^ @as(u64, pass));
                    prng.random().bytes(buf[0..n]);
                } else {
                    @memset(buf[0..n], 0);
                }
                try file.writePositionalAll(io, buf[0..n], offset);
                offset += n;
            }
        }
    }

    if (std.fs.path.isAbsolute(path)) {
        try std.Io.Dir.deleteFileAbsolute(io, path);
    } else {
        try std.Io.Dir.cwd().deleteFile(io, path);
    }
}

test "shred removes file" {
    const allocator = std.testing.allocator;
    var threaded = std.Io.Threaded.init(allocator, .{});
    defer threaded.deinit();
    const io = threaded.io();

    const name = "clip-shred-test.wav";
    {
        const f = try std.Io.Dir.cwd().createFile(io, name, .{});
        defer f.close(io);
        try f.writeStreamingAll(io, "RIFF-not-real-audio-bytes-xxxx");
    }
    try shredPath(io, name);
    std.Io.Dir.cwd().access(io, name, .{}) catch |err| {
        try std.testing.expect(err == error.FileNotFound);
        return;
    };
    return error.ShredLeftFile;
}
