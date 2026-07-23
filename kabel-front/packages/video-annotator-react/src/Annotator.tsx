import VideoAnnotator from '@kabel/video-react';
import '@kabel/video-react/dist/style.css';
import { forwardRef } from 'react';
import { MediaAnnotatorWrapper } from '@kabel/audio-annotator-react';
import type { AudioAndVideoAnnotatorRef, AnnotatorProps } from '@kabel/audio-annotator-react';

function ForwardAnnotator({ samples, ...props }: AnnotatorProps, ref: React.Ref<AudioAndVideoAnnotatorRef>) {
  return (
    <MediaAnnotatorWrapper samples={samples} ref={ref} {...props}>
      {(annotatorProps) => <VideoAnnotator {...annotatorProps} className="kabel-video-wrapper" />}
    </MediaAnnotatorWrapper>
  );
}

export const Annotator = forwardRef<AudioAndVideoAnnotatorRef, AnnotatorProps>(ForwardAnnotator);
