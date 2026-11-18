/**
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */
import { useEffect, useState, DetailedHTMLProps, HTMLAttributes } from 'react';

import { logging } from '@apache-superset/core/utils';
import { styled } from '@apache-superset/core/theme';

export type BackgroundPosition = 'top' | 'bottom';
interface ImageContainerProps {
  src: string;
  position: BackgroundPosition;
}

const ImageContainer = styled.div<ImageContainerProps>`
  background-image: url(${({ src }) => src});
  background-size: cover;
  background-position: center ${({ position }) => position};
  display: inline-block;
  height: calc(100% - 1px);
  width: calc(100% - 2px);
  margin: 1px 1px 0 1px;
`;
interface ImageLoaderProps extends DetailedHTMLProps<
  HTMLAttributes<HTMLDivElement>,
  HTMLDivElement
> {
  fallback: string;
  src: string;
  isLoading?: boolean;
  position: BackgroundPosition;
}

export function ImageLoader({
  src,
  fallback,
  isLoading,
  position,
  ...rest
}: ImageLoaderProps) {
  const [imgSrc, setImgSrc] = useState<string>(fallback);

  useEffect(() => {
    let disposed = false;
    let objectUrl: string | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let retries = 0;

    async function loadImage() {
      try {
        const response = await fetch(src);
        if (disposed) return;
        // A cold thumbnail returns 202, then may return 404 during capture.
        if (
          response.status === 202 ||
          (retries > 0 && response.status === 404)
        ) {
          if (retries < 6) {
            timer = setTimeout(loadImage, Math.min(3000 * 2 ** retries, 30000));
            retries += 1;
          }
          return;
        }
        if (!response.ok) return;
        const blob = await response.blob();
        if (!disposed && blob.type.startsWith('image/')) {
          objectUrl = URL.createObjectURL(blob);
          setImgSrc(objectUrl);
        }
      } catch (error) {
        if (!disposed) logging.error(error);
      }
    }

    setImgSrc(fallback);
    if (src) void loadImage();
    return () => {
      disposed = true;
      clearTimeout(timer);
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [src, fallback]);

  return (
    <ImageContainer
      data-test="image-loader"
      src={isLoading ? fallback : imgSrc}
      {...rest}
      position={position}
    />
  );
}
