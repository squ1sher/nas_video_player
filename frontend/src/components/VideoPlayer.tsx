type Props = {
  videoId: number;
  onError: () => void;
};

export function VideoPlayer({ videoId, onError }: Props) {
  return (
    <video
      className="video-player"
      controls
      preload="metadata"
      src={`/api/videos/${videoId}/stream`}
      onError={onError}
    />
  );
}

