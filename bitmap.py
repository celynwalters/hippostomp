#!/usr/bin/env python3
import colored_traceback.auto
from tqdm import tqdm
from PIL import Image
import textwrap

from kellog import debug, info, warning, error

# ==================================================================================================
class Bitmap():
	headerSize = 680
	bitmapRecordSize = 200
	isometricTileWidth = 58
	isometricTileHeight = 30
	isometricTileBytes = 1800
	isometricLargeTileWidth = 78
	isometricLargeTileHeight = 40
	isometricLargeTileBytes = 3200
	# ----------------------------------------------------------------------------------------------
	def __init__(self, filePath, offset):
		self.filePath = filePath
		self.offset = offset
		self.images = []

		self.read_header()
		# self.read_images(includeAlpha=self.version >= 0xd6)

	# ----------------------------------------------------------------------------------------------
	def read_header(self):
		with open(self.filePath, "rb") as f:
			f.seek(self.offset)
			self.filename = f.read(65).rstrip(b"\x00").decode("ascii")
			self.comment = f.read(51).rstrip(b"\x00").decode("ascii")
			self.width = int.from_bytes(f.read(4), byteorder="little")
			self.height = int.from_bytes(f.read(4), byteorder="little")
			self.numImages = int.from_bytes(f.read(4), byteorder="little")
			self.startIndex = int.from_bytes(f.read(4), byteorder="little")
			self.endIndex = int.from_bytes(f.read(4), byteorder="little")

			f.seek(64, 1)
			self.offset = f.tell()

	# ----------------------------------------------------------------------------------------------
	def __repr__(self):
		return f"<{__class__.__name__}: {self.filename}>"

	# ----------------------------------------------------------------------------------------------
	def __str__(self):
		return textwrap.dedent(f"""
		{self.filename}
		  Comment: {self.comment}
		  Dimensions: {self.width}x{self.height}
		  Contains {self.numImages} images ({self.startIndex} to {self.endIndex})
		""").strip()

	# ----------------------------------------------------------------------------------------------
	def read_images(self, includeAlpha: bool):
		with open(self.filePath, "rb") as f:
			f.seek(self.offset)
			for record in tqdm(range(self.numImages)):
				offset = int.from_bytes(f.read(4), byteorder="little")
				length = int.from_bytes(f.read(4), byteorder="little")
				uncompressed_length = int.from_bytes(f.read(4), byteorder="little")
				f.seek(4, 1)
				invert_offset = int.from_bytes(f.read(4), byteorder="little", signed=True)
				width = int.from_bytes(f.read(2), byteorder="little", signed=True)
				height = int.from_bytes(f.read(2), byteorder="little", signed=True)
				f.seek(26, 1)
				imgType = int.from_bytes(f.read(2), byteorder="little")
				flags = f.read(4)
				debug(flags)
				debug(flags[3])
				bitmap_id = int.from_bytes(f.read(1), byteorder="little")
				f.seek(7, 1)

				if includeAlpha:
					alpha_offset = int.from_bytes(f.read(4), byteorder="little")
					alpha_length = int.from_bytes(f.read(4), byteorder="little")
				else:
					alpha_length = 0

				self.offset = f.tell()

				if record == 0:
					continue # First one is always a dummy record

				debug(f"IMAGE {record}:")
				debug(f"  offset: {offset}")
				debug(f"  length: {length}")
				debug(f"  uncompressed_length: {uncompressed_length}")
				debug(f"  invert_offset: {invert_offset}")
				debug(f"  width: {width}")
				debug(f"  height: {height}")
				debug(f"  imgType: {imgType}")
				debug(f"  flags: {flags}")
				debug(f"  bitmap_id: {bitmap_id}")

				image = b""
				with open(self.filePath.with_suffix(".555"), "rb") as f2:
					data_length = length + alpha_length
					if data_length <= 0:
						error(f"Data length invalid: {data_length}")
						continue
					f2.seek(offset - flags[0])
					buffer = b""
					for byte in range(data_length):
						buffer += f2.read(1)
					# data_read = int.from_bytes(f2.read(1), byteorder="little") # Somehow externals have 1 byte added to their offset
					# if (data_length != data_read):
					# 	if (data_read + 4 == data_length) and (f2.eof()):
					# 		# Exception for some C3 graphics: last image is 'missing' 4 bytes
					# 		warning("Not implemented")
					# 		# buffer[data_read] = buffer[data_read+1] = 0;
					# 		# buffer[data_read+2] = buffer[data_read+3] = 0;
					# debug(data_read)
					# debug(len(buffer))

				if imgType in [0, 1, 10, 12, 13]:
					print("Plain")
					# continue
					i = 0
					for y in range(width):
						for x in range(height):
							pixel = self.set555Pixel(buffer[i] | (buffer[i + 1] << 8), width)
							image += pixel.to_bytes(4, "little")
							i += 2
					image = Image.frombuffer("RGBA", (width, height), image, "raw")
					self.images.append(image)
				elif imgType == 30:
					print("Isometric")
					# writeIsometricBase(img, pixels, buffer);
					# writeTransparentImage(img, pixels, &buffer[img->workRecord->uncompressed_length], img->workRecord->length - img->workRecord->uncompressed_length);
					size = flags[3]
					if size == 0:
						# Derive the tile size from the height (more regular than width)
						# Note that this causes a problem with 4x4 regular vs 3x3 large:
						# 4 * 30 = 120; 3 * 40 = 120 -- give precedence to regular
						if height % self.isometricTileHeight == 0:
							size = height / self.isometricTileHeight
						elif height % self.isometricLargeTileHeight == 0:
							size = height / self.isometricLargeTileHeight

					# Determine whether we should use the regular or large (emperor) tiles
					if self.isometricTileHeight * size == height:
						tileBytes = self.isometricTileBytes
						tileHeight = self.isometricTileHeight
						tileWidth = self.isometricTileWidth
					elif self.isometricLargeTileHeight * size == height:
						tileBytes = self.isometricLargeTileBytes
						tileHeight = self.isometricLargeTileHeight
						tileWidth = self.isometricLargeTileWidth
					else:
						error("Unknown tile size")
						continue

					# Check if buffer length is enough: (width + 2) * height / 2 * 2bpp */
					if (width + 2) * height != uncompressed_length:
						error("Data length doesn't match footprint size")
						continue

					i = 0
					for y in range(size + (size - 1)):
						x_offset = size - y - 1 if y < size else y - size + 1
						x_offset *= tileHeight
						wd = y + 1 if y < size else 2 * size - y - 1
						for x in range(wd):
							# writeIsometricTile(img, pixels, &buffer[i * tileBytes], x_offset, y_offset, tileWidth, tileHeight)

							halfHeight = tileHeight / 2
							x, y, i = 0, 0, 0
							for y in range(halfHeight):
								start = tileHeight - 2 * (y + 1)
								end = tileWidth - start
								for x in range(start, end):
									pixel = self.set555Pixel((buffer[i + 1] << 8) | buffer[i], wd)
									image += pixel.to_bytes(4, "little")
									i += 2
							for y in range(halfHeight, tileHeight):
								start = 2 * y - tileHeight
								end = tileWidth - start
								for x in range(start, end):
									pixel = self.set555Pixel((buffer[i + 1] << 8) | buffer[i], wd)
									image += pixel.to_bytes(4, "little")
									i += 2
							x_offset += tileWidth + 2
							i += 1
						y_offset += tileHeight / 2
						image = Image.frombuffer("RGBA", (width, height), image, "raw")
					self.images.append(image)
				elif imgType in [256, 257, 276]:
					print("Sprite")
					# continue
					i, x, y = 0, 0, 0
					while i < length:
						c = buffer[i] # uint8_t
						i += 1
						if c == 255:
							# The next byte is the number of pixels to skip
							x += buffer[i]
							for skip in range(buffer[i]):
								image += 0x00000000.to_bytes(4, "little")
							i += 1
							while (x >= width):
								y += 1
								x -= width
						else:
							# c is the number of image data bytes
							for j in range(c):
								pixel = self.set555Pixel(buffer[i] | (buffer[i + 1] << 8), width)
								image += pixel.to_bytes(4, "little")
								x += 1
								if x >= width:
									y += 1
									x = 0
								i += 2
					image = Image.frombuffer("RGBA", (width, height), image, "raw")
					self.images.append(image)
				else:
					raise ValueError(f"Unknown type: {imgType}")

	# ----------------------------------------------------------------------------------------------
	def set555Pixel(self, colour, width):
		rgba = 0xff000000
		if colour == 0xf81f:
			return rgba

		# Red: 11-15 -> 4-8 | 13-15 -> 1-3
		rgba |= ((colour & 0x7c00) >> 7) | ((colour & 0x7000) >> 12)
		# Green: 6-10 -> 12-16 | 8-10 -> 9-11
		rgba |= ((colour & 0x3e0) << 6) | ((colour & 0x380) << 1) # 0x300
		# Blue: 1-5 -> 20-24 | 3-5 -> 17-19
		rgba |= ((colour & 0x1f) << 19) | ((colour & 0x1c) << 14)

		return rgba
