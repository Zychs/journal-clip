const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    const exe = b.addExecutable(.{
        .name = "journal-clip",
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/main.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });

    if (target.result.os.tag == .windows) {
        exe.root_module.linkSystemLibrary("winmm", .{});
        exe.root_module.link_libc = true;
    }

    b.installArtifact(exe);

    const run_cmd = b.addRunArtifact(exe);
    run_cmd.step.dependOn(b.getInstallStep());
    if (b.args) |args| run_cmd.addArgs(args);
    const run_step = b.step("run", "Run journal-clip");
    run_step.dependOn(&run_cmd.step);

    var widget_tests: ?*std.Build.Step.Compile = null;

<<<<<<< Updated upstream
    // The compact widget. Win32 only, so it rides along on Windows targets and
    // is skipped elsewhere. `zig build` installs it next to journal-clip.exe.
=======
    // Compact widget. Win32 only. `zig build` installs it next to journal-clip.exe.
>>>>>>> Stashed changes
    if (target.result.os.tag == .windows) {
        const widget = b.addExecutable(.{
            .name = "journal-clip-widget",
            .root_module = b.createModule(.{
                .root_source_file = b.path("src/widget.zig"),
                .target = target,
                .optimize = optimize,
            }),
        });
<<<<<<< Updated upstream
        widget.subsystem = .windows; // no console flash behind the pane
=======
        widget.subsystem = .windows;
>>>>>>> Stashed changes
        widget.root_module.linkSystemLibrary("winmm", .{});
        widget.root_module.linkSystemLibrary("user32", .{});
        widget.root_module.linkSystemLibrary("gdi32", .{});
        widget.root_module.link_libc = true;
        b.installArtifact(widget);

        const run_widget = b.addRunArtifact(widget);
        run_widget.step.dependOn(b.getInstallStep());
        const widget_step = b.step("widget", "Run the compact widget");
        widget_step.dependOn(&run_widget.step);

        widget_tests = b.addTest(.{
            .root_module = b.createModule(.{
                .root_source_file = b.path("src/widget.zig"),
                .target = target,
                .optimize = optimize,
            }),
        });
        widget_tests.?.root_module.linkSystemLibrary("winmm", .{});
        widget_tests.?.root_module.linkSystemLibrary("user32", .{});
        widget_tests.?.root_module.linkSystemLibrary("gdi32", .{});
        widget_tests.?.root_module.link_libc = true;
    }

    const shred_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/shred.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const run_shred = b.addRunArtifact(shred_tests);
    const test_step = b.step("test", "Shred + widget unit tests");
    test_step.dependOn(&run_shred.step);
    if (widget_tests) |wt| test_step.dependOn(&b.addRunArtifact(wt).step);
}
