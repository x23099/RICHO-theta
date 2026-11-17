"""Opt-in native video for the existing driver; control channels stay in driver."""


async def run_native_driver(args,driver_run):
    from driver_frame_packet_runtime import validate_sender_args
    validate_sender_args(args)
    if not getattr(args,"motion_native",False):
        return await driver_run(args)
    if (args.cam_width,args.cam_height) != (1280,720) or args.mock_camera:
        raise ValueError("--motion-native needs real native 1280x720, NOT resized/mock input")
    from theta_rtc_diagnostic import CaptureFrames, make_native_track, open_native_capture
    capture=open_native_capture(args.device,args.fps)
    reader=CaptureFrames(capture)
    track=None
    try:
        reader.start()
        track=make_native_track(reader)
        args._motion_video_track=track
        args._motion_capture_reader=reader
        return await driver_run(args)
    finally:
        packet=getattr(args,'_frame_packet_binding',None)
        if packet is not None:
            await packet.close()
            del args._frame_packet_binding
        if track is not None:track.stop()
        reader.close()
        if hasattr(args,"_motion_video_track"):del args._motion_video_track
        if hasattr(args,'_motion_capture_reader'):del args._motion_capture_reader
