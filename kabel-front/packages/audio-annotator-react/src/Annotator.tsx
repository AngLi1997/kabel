import AudioAnnotator from '@kabel/audio-react';
import { forwardRef } from 'react';

import type { AnnotatorProps, AudioAndVideoAnnotatorRef } from './MediaAnnotatorWrapper';
import { MediaAnnotatorWrapper } from './MediaAnnotatorWrapper';

function ForwardAnnotator({ samples, ...props }: AnnotatorProps, ref: React.Ref<AudioAndVideoAnnotatorRef>) {
  return (
    <MediaAnnotatorWrapper samples={samples} ref={ref} {...props}>
      {(annotatorProps) => <AudioAnnotator {...annotatorProps} className="kabel-audio-wrapper" />}
    </MediaAnnotatorWrapper>
  );
}

ForwardAnnotator.displayName = 'AudioAnnotatorForward';

export const Annotator = forwardRef<AudioAndVideoAnnotatorRef, AnnotatorProps>(ForwardAnnotator);

Annotator.displayName = 'AudioAnnotator';
