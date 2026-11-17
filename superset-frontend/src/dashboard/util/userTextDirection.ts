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
import type { CSSProperties } from 'react';

/**
 * Inline style for inputs and text areas that hold text written by users
 * (names, descriptions), in any language.
 *
 * Each paragraph takes its base direction, and with it its alignment, from
 * its own first strong character, so punctuation of left-to-right text is not
 * reordered in a right-to-left interface and vice versa. Unlike dir="auto",
 * an empty field keeps the direction of the interface, so the caret and the
 * placeholder stay on the leading edge.
 *
 * It is an inline style on purpose: it must reach the native control, and
 * inline styles are not mirrored.
 */
export const USER_TEXT_STYLE: CSSProperties = { unicodeBidi: 'plaintext' };
