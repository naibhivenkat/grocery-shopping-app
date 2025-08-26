package com.example.groceryshoppingapp

import android.app.Activity
import android.content.Intent
import android.graphics.BitmapFactory
import android.os.Bundle
import android.util.Base64
import android.widget.*
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import com.example.groceryshoppingapp.network.ApiClient
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.utils.ImageUtils
import com.example.groceryshoppingapp.utils.SessionManager
import okhttp3.ResponseBody
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class EditProfileActivity : AppCompatActivity() {

    private lateinit var imgProfile: ImageView
    private lateinit var etName: EditText
    private lateinit var etEmail: EditText
    private lateinit var etPhone: EditText
    private lateinit var etAddress: EditText
    private lateinit var etLocation: EditText
    private lateinit var btnSave: Button
    private lateinit var btnBack: ImageButton
    private lateinit var btnChangePhoto: ImageButton

    private var selectedImageBase64: String? = null

    companion object {
        const val PICK_IMAGE_REQUEST = 1001
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_edit_profile)

        imgProfile = findViewById(R.id.img_profile)
        etName = findViewById(R.id.et_full_name)
        etEmail = findViewById(R.id.et_email)
        etPhone = findViewById(R.id.et_phone)
        etAddress = findViewById(R.id.et_address)
        etLocation = findViewById(R.id.et_location)
        btnSave = findViewById(R.id.btn_save)
        btnBack = findViewById(R.id.btn_back)
        btnChangePhoto = findViewById(R.id.btn_change_photo)

        // Pre-fill fields from session
        etName.setText(SessionManager.getFullName(this))
        etEmail.setText(SessionManager.getEmail(this))
        etPhone.setText(SessionManager.getPhone(this))
        etAddress.setText(SessionManager.getAddress(this))
        etLocation.setText(SessionManager.getLocation(this))

        // Load profile photo if exists
        val base64Image = SessionManager.getPhotoBase64(this)
        if (!base64Image.isNullOrEmpty() && base64Image != "null") {
            try {
                val decodedBytes = Base64.decode(base64Image, Base64.DEFAULT)
                val bitmap = BitmapFactory.decodeByteArray(decodedBytes, 0, decodedBytes.size)
                imgProfile.setImageBitmap(bitmap)
            } catch (e: Exception) {
                e.printStackTrace()
                Toast.makeText(this, "Failed to load profile photo", Toast.LENGTH_SHORT).show()
            }
        }

        btnBack.setOnClickListener {
            finish()
        }

        btnChangePhoto.setOnClickListener {
            openImagePicker()
        }

        imgProfile.setOnClickListener {
            openImagePicker()
        }

        btnSave.setOnClickListener {
            AlertDialog.Builder(this)
                .setTitle("Confirm")
                .setMessage("Save changes to profile?")
                .setPositiveButton("Yes") { _, _ ->
                    val name = etName.text.toString()
                    val email = etEmail.text.toString()
                    val phone = etPhone.text.toString()
                    val address = etAddress.text.toString()
                    val location = etLocation.text.toString()
                    val username = SessionManager.getUsername(this)
                    val role = SessionManager.getRole(this)

                    // Save locally
                    SessionManager.saveUserProfile(this, name, address, phone, email, location, selectedImageBase64)

                    // Prepare API call
                    val apiService: ApiService = ApiClient.apiService
                    val profileData = HashMap<String, String>()
                    profileData["username"] = username ?: ""
                    profileData["role"] = role ?: ""
                    profileData["name"] = name
                    profileData["email"] = email
                    profileData["phone"] = phone
                    profileData["address"] = address
                    profileData["location"] = location
                    if (!selectedImageBase64.isNullOrEmpty()) {
                        profileData["photo_base64"] = selectedImageBase64!!
                    }

                    apiService.updateProfile(profileData).enqueue(object : Callback<ResponseBody> {
                        override fun onResponse(call: Call<ResponseBody>, response: Response<ResponseBody>) {
                            if (response.isSuccessful) {
                                Toast.makeText(this@EditProfileActivity, "Profile updated successfully", Toast.LENGTH_SHORT).show()
                                finish()
                            } else {
                                Toast.makeText(this@EditProfileActivity, "Failed to update profile on server", Toast.LENGTH_SHORT).show()
                            }
                        }

                        override fun onFailure(call: Call<ResponseBody>, t: Throwable) {
                            Toast.makeText(this@EditProfileActivity, "Error: ${t.message}", Toast.LENGTH_SHORT).show()
                        }
                    })
                }
                .setNegativeButton("Cancel", null)
                .show()
        }
    }

    private fun openImagePicker() {
        val intent = Intent(Intent.ACTION_GET_CONTENT)
        intent.type = "image/*"
        intent.addCategory(Intent.CATEGORY_OPENABLE)
        startActivityForResult(Intent.createChooser(intent, "Select Picture"), PICK_IMAGE_REQUEST)
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (resultCode == Activity.RESULT_OK && requestCode == PICK_IMAGE_REQUEST && data != null && data.data != null) {
            val uri = data.data
            val bitmap = ImageUtils.getBitmapFromUri(this, uri!!)
            if (bitmap != null) {
                imgProfile.setImageBitmap(bitmap)
                selectedImageBase64 = ImageUtils.bitmapToBase64(bitmap)
            } else {
                Toast.makeText(this, "Failed to load image", Toast.LENGTH_SHORT).show()
            }
        }
    }
}
