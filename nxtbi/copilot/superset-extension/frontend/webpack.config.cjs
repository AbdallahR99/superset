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
const path = require('node:path');

const frontend = path.resolve(__dirname, '../../../../superset-frontend');
const dependencies = path.join(frontend, 'node_modules');
const packages = path.join(frontend, 'packages');
const { ModuleFederationPlugin } = require(
  path.join(dependencies, 'webpack'),
).container;
const MiniCssExtractPlugin = require(
  path.join(dependencies, 'mini-css-extract-plugin'),
);
const hostPackage = require(path.join(frontend, 'package.json'));

const shared = Object.fromEntries(
  ['react', 'react-dom', 'antd', '@apache-superset/core'].map(name => [
    name,
    {
      singleton: true,
      import: false,
      requiredVersion:
        name === '@apache-superset/core'
          ? false
          : hostPackage.dependencies[name],
    },
  ]),
);

module.exports = {
  mode: 'production',
  context: __dirname,
  entry: {},
  output: {
    clean: true,
    chunkFilename: '[name].[contenthash].js',
    path: path.join(__dirname, 'dist'),
    publicPath: 'auto',
    uniqueName: 'nxtbi_aiCopilot',
  },
  resolve: {
    extensions: ['.ts', '.tsx', '.js', '.jsx', '.json'],
    modules: ['node_modules', dependencies, frontend],
    alias: {
      '@apache-superset/core': path.join(packages, 'superset-core/src'),
      '@apache-superset/widgets': path.join(packages, 'superset-widgets/src'),
      '@superset-ui/core': path.join(packages, 'superset-ui-core/src'),
      '@nxtbi/copilot$': path.join(packages, 'nxtbi-copilot/src/index.ts'),
      '@nxtbi/copilot/styles.css$': path.join(
        packages,
        'nxtbi-copilot/src/styles.css',
      ),
    },
  },
  resolveLoader: { modules: [dependencies] },
  module: {
    rules: [
      {
        test: /\.tsx?$/,
        exclude: /node_modules/,
        loader: 'swc-loader',
        options: {
          jsc: {
            parser: { syntax: 'typescript', tsx: true },
            target: 'es2020',
            transform: {
              react: { runtime: 'automatic', importSource: '@emotion/react' },
            },
          },
        },
      },
      {
        test: /\.css$/,
        use: [MiniCssExtractPlugin.loader, 'css-loader'],
      },
      {
        test: /\.svg$/,
        issuer: /\.[jt]sx?$/,
        loader: '@svgr/webpack',
        options: { ref: true, titleProp: true },
      },
      {
        test: /\.(png|jpe?g|gif|woff2?)$/,
        type: 'asset/resource',
      },
    ],
  },
  plugins: [
    new MiniCssExtractPlugin({ chunkFilename: '[name].[contenthash].css' }),
    new ModuleFederationPlugin({
      name: 'nxtbi_aiCopilot',
      filename: 'remoteEntry.[contenthash].js',
      exposes: { './index': './src/index.tsx' },
      shared,
    }),
  ],
};
