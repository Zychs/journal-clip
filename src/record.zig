//! Isolated WinMM capture. Device index from change-input. No host.

const std = @import("std");
const builtin = @import("builtin");

pub const HWAVEIN = *anyopaque;

pub const WAVEFORMATEX = extern struct {
    wFormatTag: u16,
    nChannels: u16,
    nSamplesPerSec: u32,
    nAvgBytesPerSec: u32,
    nBlockAlign: u16,
    wBitsPerSample: u16,
    cbSize: u16,
};

pub const WAVEHDR = extern struct {
    lpData: [*]u8,
    dwBufferLength: u32,
    dwBytesRecorded: u32,
    dwUser: usize,
    dwFlags: u32,
    dwLoops: u32,
    lpNext: ?*WAVEHDR,
    reserved: usize,
};

pub extern "winmm" fn waveInOpen(
    phwi: *?HWAVEIN,
    uDeviceID: u32,
    pwfx: *const WAVEFORMATEX,
    dwCallback: usize,
    dwInstance: usize,
    fdwOpen: u32,
) callconv(.winapi) u32;

pub extern "winmm" fn waveInPrepareHeader(hwi: HWAVEIN, pwh: *WAVEHDR, cbwh: u32) callconv(.winapi) u32;
pub extern "winmm" fn waveInUnprepareHeader(hwi: HWAVEIN, pwh: *WAVEHDR, cbwh: u32) callconv(.winapi) u32;
pub extern "winmm" fn waveInAddBuffer(hwi: HWAVEIN, pwh: *WAVEHDR, cbwh: u32) callconv(.winapi) u32;
pub extern "winmm" fn waveInStart(hwi: HWAVEIN) callconv(.winapi) u32;
pub extern "winmm" fn waveInStop(hwi: HWAVEIN) callconv(.winapi) u32;
pub extern "winmm" fn waveInReset(hwi: HWAVEIN) callconv(.winapi) u32;
pub extern "winmm" fn waveInClose(hwi: HWAVEIN) callconv(.winapi) u32;
pub extern "kernel32" fn Sleep(dwMilliseconds: u32) callconv(.winapi) void;

pub fn writeWavHeader(writer: *std.Io.Writer, data_size: u32, sample_rate: u32, channels: u16, bits_per_sample: u16) !void {
    try writer.writeAll("RIFF");
    try writer.writeInt(u32, data_size + 36, .little);
    try writer.writeAll("WAVEfmt ");
    try writer.writeInt(u32, 16, .little);
    try writer.writeInt(u16, 1, .little);
    try writer.writeInt(u16, channels, .little);
    try writer.writeInt(u32, sample_rate, .little);
    const byte_rate = (sample_rate * channels * bits_per_sample) / 8;
    try writer.writeInt(u32, byte_rate, .little);
    const block_align = (channels * bits_per_sample) / 8;
    try writer.writeInt(u16, block_align, .little);
    try writer.writeInt(u16, bits_per_sample, .little);
    try writer.writeAll("data");
    try writer.writeInt(u32, data_size, .little);
}

fn createWav(io: std.Io, file_path: []const u8) !std.Io.File {
    if (std.fs.path.isAbsolute(file_path)) {
        return std.Io.Dir.createFileAbsolute(io, file_path, .{});
    }
    return std.Io.Dir.cwd().createFile(io, file_path, .{});
}

pub fn generateMockWav(file_path: []const u8, duration_seconds: f32, io: std.Io) !void {
    const file = try createWav(io, file_path);
    defer file.close(io);

    const sample_rate: u32 = 16000;
    const channels: u16 = 1;
    const bits_per_sample: u16 = 16;
    const num_samples = @as(u32, @intFromFloat(duration_seconds * @as(f32, @floatFromInt(sample_rate))));
    const data_size = num_samples * 2;

    var write_buf: [1024]u8 = undefined;
    var file_writer = file.writer(io, &write_buf);
    const writer = &file_writer.interface;
    try writeWavHeader(writer, data_size, sample_rate, channels, bits_per_sample);

    const freq = 440.0;
    const two_pi = 2.0 * std.math.pi;
    var i: u32 = 0;
    while (i < num_samples) : (i += 1) {
        const t = @as(f64, @floatFromInt(i)) / @as(f64, @floatFromInt(sample_rate));
        const val_f = std.math.sin(two_pi * freq * t);
        const val_i = @as(i16, @intFromFloat(val_f * 32767.0));
        try writer.writeInt(i16, val_i, .little);
    }
    try file_writer.flush();
}

/// Record `duration_seconds` from WinMM device `device_index` (change-input).
pub fn recordAudio(
    file_path: []const u8,
    duration_seconds: f32,
    device_index: u32,
    allocator: std.mem.Allocator,
    io: std.Io,
) !void {
    if (builtin.os.tag != .windows) {
        std.debug.print("[clip] not Windows - mock wav\n", .{});
        return generateMockWav(file_path, duration_seconds, io);
    }

    const sample_rate: u32 = 16000;
    const channels: u16 = 1;
    const bits_per_sample: u16 = 16;
    const num_samples = @as(u32, @intFromFloat(duration_seconds * @as(f32, @floatFromInt(sample_rate))));
    const data_size = num_samples * 2;
    const buffer = try allocator.alloc(u8, data_size);
    defer allocator.free(buffer);
    @memset(buffer, 0);

    const wfx = WAVEFORMATEX{
        .wFormatTag = 1,
        .nChannels = channels,
        .nSamplesPerSec = sample_rate,
        .nAvgBytesPerSec = sample_rate * channels * (bits_per_sample / 8),
        .nBlockAlign = channels * (bits_per_sample / 8),
        .wBitsPerSample = bits_per_sample,
        .cbSize = 0,
    };

    var hwi: ?HWAVEIN = null;
    const open_res = waveInOpen(&hwi, device_index, &wfx, 0, 0, 0);
    if (open_res != 0) {
        std.debug.print("[clip] waveInOpen device {d} failed ({d}). mock wav.\n", .{ device_index, open_res });
        return generateMockWav(file_path, duration_seconds, io);
    }
    const h = hwi.?;
    defer _ = waveInClose(h);

    var whdr = WAVEHDR{
        .lpData = buffer.ptr,
        .dwBufferLength = data_size,
        .dwBytesRecorded = 0,
        .dwUser = 0,
        .dwFlags = 0,
        .dwLoops = 0,
        .lpNext = null,
        .reserved = 0,
    };
    if (waveInPrepareHeader(h, &whdr, @sizeOf(WAVEHDR)) != 0 or
        waveInAddBuffer(h, &whdr, @sizeOf(WAVEHDR)) != 0 or
        waveInStart(h) != 0)
    {
        std.debug.print("[clip] winmm start failed. mock wav.\n", .{});
        return generateMockWav(file_path, duration_seconds, io);
    }

    std.debug.print("[clip] speak - recording {d:.0}s on device {d}\n", .{ duration_seconds, device_index });
    Sleep(@intCast(@as(u64, @intFromFloat(duration_seconds * 1000.0))));
    _ = waveInStop(h);
    _ = waveInReset(h);

    const file = try createWav(io, file_path);
    defer file.close(io);
    var write_buf: [1024]u8 = undefined;
    var file_writer = file.writer(io, &write_buf);
    const writer = &file_writer.interface;
    const nbytes: u32 = if (whdr.dwBytesRecorded > 0) whdr.dwBytesRecorded else data_size;
    try writeWavHeader(writer, nbytes, sample_rate, channels, bits_per_sample);
    try writer.writeAll(buffer[0..@as(usize, nbytes)]);
    try file_writer.flush();
    std.debug.print("[clip] temp wav {s} ({d} bytes)\n", .{ file_path, nbytes });
}
