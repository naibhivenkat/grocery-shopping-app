package com.example.groceryshoppingapp.utils

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.ImageDecoder
import android.net.Uri
import android.os.Build
import android.provider.MediaStore
import android.util.Base64
import java.io.ByteArrayOutputStream

object ImageUtils {
    const val REQUEST_IMAGE_PICK = 1001


    fun getBitmapFromUri(context: Context, uri: Uri): Bitmap? {
        return try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                val source = ImageDecoder.createSource(context.contentResolver, uri)
                ImageDecoder.decodeBitmap(source)
            } else {
                MediaStore.Images.Media.getBitmap(context.contentResolver, uri)
            }
        } catch (e: Exception) {
            e.printStackTrace()
            null
        }
    }

    fun bitmapToBase64(bitmap: Bitmap): String {
        // ✅ Resize: Max width = 300px (maintain aspect ratio)
        val maxWidth = 300
        val resizedBitmap = if (bitmap.width > maxWidth) {
            val aspectRatio = bitmap.height.toFloat() / bitmap.width
            Bitmap.createScaledBitmap(bitmap, maxWidth, (maxWidth * aspectRatio).toInt(), true)
        } else {
            bitmap
        }

        // ✅ Compress: JPEG format at 70% quality
        val outputStream = ByteArrayOutputStream()
        resizedBitmap.compress(Bitmap.CompressFormat.JPEG, 70, outputStream)
        val byteArray = outputStream.toByteArray()

        // ✅ Convert to Base64 string
        return Base64.encodeToString(byteArray, Base64.NO_WRAP)
    }

}
