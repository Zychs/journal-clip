//! Isolated journal clip. No host, no dashboard, no Circadia.
//! Zig: record + orchestrate + write + shred the scratch wav.
//! Python: archive audio + whisper + nomic + 7B.
//!
//! One take makes three products, kept apart on purpose:
//!   raw audio   never overwritten  (python/clip_audio.py)
//!   transcript  versioned by model (python/clip_transcript.py)
//!   semantics   revisable guesses  (python/clip_semantics.py)
//!
//! The shred below destroys only this process's *temp* wav. The sidecar has
//! already copied the take into the raw-audio store by the time it returns.

const std = @import("std");
const builtin = @import("builtin");
const record = @import("record.zig");
const shred = @import("shred.zig");

extern "kernel32" fn GetSystemTimeAsFileTime(lpSystemTimeAsFileTime: *u64) callconv(.winapi) void;

fn nowStamp() u64 {
    if (builtin.os.tag == .windows) {
        var ft: u64 = 0;
        GetSystemTimeAsFileTime(&ft);
        return ft;
    }
    return 1;
}

const Heavy = struct {
    ok: bool = false,
    @"error": ?[]const u8 = null,
    kind: ?[]const u8 = null,
    structured: ?[]const u8 = null,
    dest_rel: ?[]const u8 = null,
    out_dir: ?[]const u8 = null,
    transcript: ?[]const u8 = null,
    prompt_source: ?[]const u8 = null,
    audio_uid: ?[]const u8 = null,
    audio_path: ?[]const u8 = null,
    audio_retained: bool = false,
};

const FileCfg = struct {
    out_dir: ?[]const u8 = null,
    input_index: ?i64 = null,
};

fn usage() void {
    std.debug.print(
        \\sesefus journal-clip (isolated)
        \\
        \\  journal-clip                     speak → audio kept, text landed
        \\  journal-clip --seconds N         record length (default 10)
        \\  journal-clip --file path.wav     skip mic (does not delete source)
        \\  journal-clip --say "text"        skip mic + whisper (no audio product)
        \\  journal-clip --no-llm            skip 7B (tests)
        \\
        \\controls (persist in %USERPROFILE%\.sesefus\clip-config.json)
        \\  journal-clip change-dir [PATH]           output journal root
        \\  journal-clip change-input [INDEX]        capture device; omit to list
        \\  journal-clip change-prompt [FILE]        LLM / structure; --kind ID; --clear
        \\  journal-clip change-audio [MODE]         archive (default) | shred
        \\  journal-clip status                      compile/run check (no record)
        \\
        \\three products under the journal root, three preservation rules
        \\  audio/       raw wav      never overwritten
        \\  transcript/  the words    a new version per transcription model
        \\  semantics/   tags, gist   revisable model output, not ground truth
        \\  takes.jsonl  flat view    a projection; rebuild with clip_store project
        \\
    , .{});
}

fn findPython(allocator: std.mem.Allocator, io: std.Io, env: anytype) ![]const u8 {
    if (env.get("SESEFUS_CLIP_PYTHON")) |p| {
        return try allocator.dupe(u8, p);
    }
    const cwd = std.Io.Dir.cwd();
    const candidates = [_][]const u8{
        "..\\venv\\Scripts\\python.exe",
        "..\\..\\..\\venv\\Scripts\\python.exe",
        "venv\\Scripts\\python.exe",
    };
    for (candidates) |c| {
        cwd.access(io, c, .{}) catch continue;
        return try allocator.dupe(u8, c);
    }
    return try allocator.dupe(u8, if (builtin.os.tag == .windows) "python" else "python3");
}

fn findScript(allocator: std.mem.Allocator, io: std.Io, env: anytype, name: []const u8) ![]const u8 {
    const env_key = if (std.mem.eql(u8, name, "clip_heavy.py"))
        "SESEFUS_CLIP_HEAVY"
    else
        "SESEFUS_CLIP_CONFIG_PY";
    if (env.get(env_key)) |p| {
        return try allocator.dupe(u8, p);
    }
    const prefixes = [_][]const u8{
        "python/",
        "../python/",
        "../../python/",
        "apps/journal-clip/python/",
    };
    const cwd = std.Io.Dir.cwd();
    for (prefixes) |prefix| {
        const cand = try std.fmt.allocPrint(allocator, "{s}{s}", .{ prefix, name });
        cwd.access(io, cand, .{}) catch {
            allocator.free(cand);
            continue;
        };
        return cand;
    }
    return error.ScriptNotFound;
}

fn spawnPython(
    io: std.Io,
    argv: []const []const u8,
) !void {
    var child = try std.process.spawn(io, .{
        .argv = argv,
        .stdin = .inherit,
        .stdout = .inherit,
        .stderr = .inherit,
    });
    _ = try child.wait(io);
}

fn forwardCtrl(allocator: std.mem.Allocator, io: std.Io, env: anytype, args: []const []const u8) !void {
    const py = try findPython(allocator, io, env);
    defer allocator.free(py);
    const script = findScript(allocator, io, env, "clip_config.py") catch {
        std.debug.print("[clip] clip_config.py not found\n", .{});
        return error.ScriptNotFound;
    };
    defer allocator.free(script);

    var argv = std.ArrayList([]const u8).empty;
    defer argv.deinit(allocator);
    try argv.append(allocator, py);
    try argv.append(allocator, script);
    for (args) |a| try argv.append(allocator, a);
    try spawnPython(io, argv.items);
}

fn readFileAlloc(allocator: std.mem.Allocator, io: std.Io, path: []const u8) ![]u8 {
    const file = if (std.fs.path.isAbsolute(path))
        try std.Io.Dir.openFileAbsolute(io, path, .{ .mode = .read_only })
    else
        try std.Io.Dir.cwd().openFile(io, path, .{ .mode = .read_only });
    defer file.close(io);
    var read_buf: [4096]u8 = undefined;
    var reader = file.reader(io, &read_buf);
    return try reader.interface.allocRemaining(allocator, .unlimited);
}

fn loadInputIndex(allocator: std.mem.Allocator, io: std.Io, env: anytype) u32 {
    const path = blk: {
        if (env.get("SESEFUS_CLIP_CONFIG")) |p| break :blk allocator.dupe(u8, p) catch return 0;
        const home = env.get("USERPROFILE") orelse return 0;
        break :blk std.fmt.allocPrint(allocator, "{s}\\.sesefus\\clip-config.json", .{home}) catch return 0;
    };
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

fn writeJournal(allocator: std.mem.Allocator, io: std.Io, heavy: Heavy) ![]u8 {
    const out_dir = heavy.out_dir orelse return error.NoOutDir;
    const rel = heavy.dest_rel orelse return error.NoDest;
    const structured = heavy.structured orelse "";
    const kind = heavy.kind orelse "dump";

    const full = try std.fs.path.join(allocator, &.{ out_dir, rel });
    if (std.mem.endsWith(u8, rel, ".csv")) {
        return full;
    }
    if (std.fs.path.dirname(full)) |dir| makeDirAll(io, dir);

    var body = std.ArrayList(u8).empty;
    errdefer body.deinit(allocator);
    try body.appendSlice(allocator, "---\nkind: ");
    try body.appendSlice(allocator, kind);
    try body.appendSlice(allocator, "\nclip: journal-clip\nembed_on: text\n---\n\n");
    try body.appendSlice(allocator, structured);
    if (structured.len == 0 or structured[structured.len - 1] != '\n') {
        try body.append(allocator, '\n');
    }

    const file = if (std.fs.path.isAbsolute(full))
        try std.Io.Dir.createFileAbsolute(io, full, .{ .truncate = true })
    else
        try std.Io.Dir.cwd().createFile(io, full, .{});
    defer file.close(io);
    try file.writeStreamingAll(io, body.items);
    body.deinit(allocator);
    return full;
}

fn makeDirAll(io: std.Io, path: []const u8) void {
    if (path.len == 0) return;
    std.Io.Dir.cwd().createDirPath(io, path) catch {};
}

fn runClip(
    allocator: std.mem.Allocator,
    io: std.Io,
    env: anytype,
    args: []const []const u8,
) !void {
    var seconds: f32 = 10;
    var file_wav: ?[]const u8 = null;
    var say: ?[]const u8 = null;
    var no_llm = false;
    var i: usize = 1;
    while (i < args.len) : (i += 1) {
        if (std.mem.eql(u8, args[i], "--seconds") and i + 1 < args.len) {
            i += 1;
            seconds = std.fmt.parseFloat(f32, args[i]) catch 10;
        } else if (std.mem.eql(u8, args[i], "--file") and i + 1 < args.len) {
            i += 1;
            file_wav = args[i];
        } else if (std.mem.eql(u8, args[i], "--say") and i + 1 < args.len) {
            i += 1;
            say = args[i];
        } else if (std.mem.eql(u8, args[i], "--no-llm")) {
            no_llm = true;
        } else if (std.mem.eql(u8, args[i], "--help") or std.mem.eql(u8, args[i], "-h")) {
            usage();
            return;
        }
    }

    const py = try findPython(allocator, io, env);
    defer allocator.free(py);
    const heavy_py = findScript(allocator, io, env, "clip_heavy.py") catch {
        std.debug.print("[clip] clip_heavy.py not found\n", .{});
        return error.ScriptNotFound;
    };
    defer allocator.free(heavy_py);

    var own_wav = false;
    var wav_path: ?[]u8 = null;
    defer if (wav_path) |p| allocator.free(p);

    const tmp_dir = env.get("TEMP") orelse env.get("TMP") orelse "C:\\Windows\\Temp";
    const stamp = nowStamp();

    if (say == null and file_wav == null) {
        wav_path = try std.fmt.allocPrint(allocator, "{s}\\sesefus-clip-{d}.wav", .{ tmp_dir, stamp });
        own_wav = true;
        const idx = loadInputIndex(allocator, io, env);
        try record.recordAudio(wav_path.?, seconds, idx, allocator, io);
    }

    const out_json = try std.fmt.allocPrint(allocator, "{s}\\sesefus-clip-{d}.json", .{ tmp_dir, stamp });
    defer allocator.free(out_json);

    var argv = std.ArrayList([]const u8).empty;
    defer argv.deinit(allocator);
    try argv.append(allocator, py);
    try argv.append(allocator, heavy_py);
    try argv.append(allocator, "--out");
    try argv.append(allocator, out_json);
    if (no_llm) try argv.append(allocator, "--no-llm");
    if (say) |t| {
        try argv.append(allocator, "--text");
        try argv.append(allocator, t);
    } else if (file_wav) |f| {
        try argv.append(allocator, "--wav");
        try argv.append(allocator, f);
    } else if (wav_path) |w| {
        try argv.append(allocator, "--wav");
        try argv.append(allocator, w);
    }

    spawnPython(io, argv.items) catch |err| {
        if (own_wav) {
            if (wav_path) |w| shred.shredPath(io, w) catch {};
        }
        std.debug.print("[clip] heavy sidecar failed: {s}\n", .{@errorName(err)});
        return err;
    };
    if (own_wav) {
        if (wav_path) |w| {
            shred.shredPath(io, w) catch |err| {
                std.debug.print("[clip] shred failed: {s}\n", .{@errorName(err)});
            };
        }
    }

    const raw = try readFileAlloc(allocator, io, out_json);
    defer allocator.free(raw);
    const parsed = try std.json.parseFromSlice(Heavy, allocator, raw, .{ .ignore_unknown_fields = true });
    defer parsed.deinit();
    if (!parsed.value.ok) {
        std.debug.print("[clip] {s}\n", .{parsed.value.@"error" orelse "heavy failed"});
        return error.HeavyFailed;
    }

    const dest_dir_join = parsed.value.out_dir orelse "";
    const dest_rel = parsed.value.dest_rel orelse "";
    const dest_parent = std.fs.path.dirname(dest_rel) orelse "";
    const abs_parent = try std.fs.path.join(allocator, &.{ dest_dir_join, dest_parent });
    defer allocator.free(abs_parent);
    makeDirAll(io, abs_parent);

    const written = try writeJournal(allocator, io, parsed.value);
    defer allocator.free(written);
    std.debug.print("[clip] wrote {s}\n", .{written});
    if (parsed.value.audio_retained) {
        std.debug.print("[clip] kept audio {s}\n", .{parsed.value.audio_path orelse ""});
    }
    if (parsed.value.prompt_source) |ps| {
        std.debug.print("[clip] prompt {s}\n", .{ps});
    }
    shred.shredPath(io, out_json) catch {};
}

pub fn main(init: std.process.Init) !void {
    const allocator = init.gpa;
    const io = init.io;
    const env = init.environ_map;
    const args = try init.minimal.args.toSlice(init.arena.allocator());

    if (args.len >= 2) {
        const cmd = args[1];
        if (std.mem.eql(u8, cmd, "status")) {
            std.debug.print("[clip] journal-clip ok\n", .{});
            try forwardCtrl(allocator, io, env, &.{"show"});
            return;
        }
        if (std.mem.eql(u8, cmd, "change-dir") or
            std.mem.eql(u8, cmd, "change-input") or
            std.mem.eql(u8, cmd, "change-prompt") or
            std.mem.eql(u8, cmd, "change-audio") or
            std.mem.eql(u8, cmd, "show"))
        {
            try forwardCtrl(allocator, io, env, args[1..]);
            return;
        }
        if (std.mem.eql(u8, cmd, "--help") or std.mem.eql(u8, cmd, "-h") or std.mem.eql(u8, cmd, "help")) {
            usage();
            return;
        }
    }
    try runClip(allocator, io, env, args);
}
