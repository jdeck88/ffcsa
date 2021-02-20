// inspired by https://github.com/matthiask/workbench/tree/39a4287b45fc7a1b59a3eb9dfd9f11ef461c3834
const CWD = process.cwd()

const path = require('path')
const webpack = require('webpack')

const BundleTracker = require('webpack-bundle-tracker')
const MiniCssExtractPlugin = require('mini-css-extract-plugin')
const {CleanWebpackPlugin} = require('clean-webpack-plugin')
const TerserJSPlugin = require('terser-webpack-plugin')
const OptimizeCSSAssetsPlugin = require('optimize-css-assets-webpack-plugin')
const packageJson = require(path.resolve(CWD, 'package.json'))

// const HOST = process.env.HOST || '127.0.0.1'
const HOST = process.env.HOST || '198.199.109.231'
const DEBUG = process.env.NODE_ENV !== 'production'
const HTTPS = !!process.env.HTTPS

config = {
  mode: DEBUG ? 'development' : 'production',
  // bail: DEBUG ? false : true,
  devtool: 'source-map',
  entry: {
    // main: './main.js',
    style: './ffcsa/static/css/style-source.css',
    // cart: './cart/index.js',
    // absences: './absences/index.js',
  },
  // context: path.join(CWD, "app", "static", "app"),
  context: path.join(__dirname),
  output: {
    path: path.resolve('./static/ffcsa/'),
    publicPath: DEBUG
      ? 'http' + (HTTPS ? 's' : '') + '://' + HOST + ':4000/'
      : (process.env.STATIC_URL || '/static/') + 'ffcsa/',
    filename: DEBUG ? '[name].js' : '[name]-[contenthash].js',
  },
  module: {
    rules: [
      {
        test: /\.css$/,
        use: ['style-loader', 'css-loader', 'postcss-loader'],
      },
      {
        test: /\.scss$/,
        use: ['sass-loader'],
      },
      {
        test: /\.(png|woff|woff2|svg|eot|ttf|gif|jpe?g)$/,
        use: [
          {
            loader: 'url-loader',
            options: {
              limit: 500,
              // ManifestStaticFilesStorage reuse.
              name: '[path][name].[md5:hash:hex:12].[ext]',
              // No need to emit files in production, collectstatic does it.
            },
          },
        ],
      },
    ]
  },
  plugins: [
    // NOTE - below lines are commented out cuz they cuz 'Invalid configuration' for development config
    // DEBUG ? null : new webpack.optimize.SplitChunksPlugin(),
    // DEBUG ? null : new CleanWebpackPlugin(),
    // DEBUG
    //   ? null
    //   : new MiniCssExtractPlugin({
    //     filename: '[name]-[contenthash].css',
    //   }),
    new BundleTracker({
      filename: './static/webpack-stats-' + (DEBUG ? 'dev' : 'prod') + '.json',

      // path: path.resolve(__dirname, "static/"),
      // publicPath: "/",
      // filename: "webpack-stats-dev.js"
    }),
    new webpack.HashedModuleIdsPlugin(),
  ],
  devServer: {
    contentBase: false,
    inline: true,
    quiet: false,
    https: HTTPS,
    disableHostCheck: true,
    headers: {'Access-Control-Allow-Origin': '*'},
    host: HOST,
    historyApiFallback: true,
    hot: true,
    stats: "minimal",
    // host: "localhost",
    host: "0.0.0.0",
    port: 4000,
  },
  performance: {
    // No point warning in development, since HMR / CSS bundling blows up
    // the asset / entrypoint size anyway.
    hints: DEBUG ? false : 'warning',
  },
  optimization: {
    minimizer: [
      new TerserJSPlugin({}),
      new OptimizeCSSAssetsPlugin({
        cssProcessorPluginOptions: {
          preset: [
            'default',
            {
              svgo: false,
            },
          ],
        },
      }),
    ],
    // splitChunks: {
    //   cacheGroups: {
    //     vendors: {
    //       test: /\/node_modules\//,
    //       name: 'vendors',
    //       chunks: 'all',
    //     },
    //   },
    // },
    // runtimeChunk: {
    //   name: 'manifest',
    // },
  },
}

module.exports = config
