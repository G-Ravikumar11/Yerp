require 'json'

package = JSON.parse(File.read(File.join(__dir__, 'package.json')))

Pod::Spec.new do |s|
  s.name = 'YerpGlass'
  s.version = package['version']
  s.summary = package['description']
  s.license = package['license']
  s.homepage = 'https://github.com/G-Ravikumar11/Yerp'
  s.author = 'Yerp'
  s.source = { :git => 'https://github.com/G-Ravikumar11/Yerp.git', :tag => s.version.to_s }
  # The plugin's own two files, plus LiquidGlassKit's sources, which the iOS build copies into ios/Sources/LiquidGlassKit
  # (scripts/add-liquidglasskit.sh) so the library is compiled inside this pod.
  s.source_files = 'ios/Sources/**/*.{swift,h,m}'
  s.ios.deployment_target = '17.0'
  s.dependency 'Capacitor'
  s.swift_version = '5.1'
end
