package com.example.groceryshoppingapp

import android.content.Intent
import android.graphics.BitmapFactory
import android.os.Bundle
import android.util.Base64
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import com.example.groceryshoppingapp.utils.SessionManager
import com.google.android.material.appbar.MaterialToolbar

class ProfileActivity : AppCompatActivity() {

    private lateinit var imgProfile: ImageView
    private lateinit var tvName: TextView
    private lateinit var tvEmail: TextView
    private lateinit var tvPhone: TextView
    private lateinit var tvAddress: TextView
    private lateinit var tvLocation: TextView
    private lateinit var btnEdit: Button
    private lateinit var toolbar: MaterialToolbar

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_profile)

        // Initialize Toolbar
        toolbar = findViewById(R.id.toolbar_profile)
        setSupportActionBar(toolbar)
        supportActionBar?.title = "Profile" // optional, already set in XML
        toolbar.setNavigationOnClickListener {
            finish() // back arrow pressed
        }

        // Initialize views
        imgProfile = findViewById(R.id.img_profile)
        tvName = findViewById(R.id.tv_name)
        tvEmail = findViewById(R.id.tv_email)
        tvPhone = findViewById(R.id.tv_phone)
        tvAddress = findViewById(R.id.tv_address)
        tvLocation = findViewById(R.id.tv_location)
        btnEdit = findViewById(R.id.btn_edit)

        // Load profile data from SessionManager
        tvName.text = SessionManager.getFullName(this)
        tvEmail.text = SessionManager.getEmail(this)
        tvPhone.text = SessionManager.getPhone(this)
        tvAddress.text = SessionManager.getAddress(this)
        tvLocation.text = SessionManager.getLocation(this)

        // Show profile image from Base64
        val base64Image = SessionManager.getPhotoBase64(this)
        if (!base64Image.isNullOrBlank()) {
            try {
                val imageBytes = Base64.decode(base64Image, Base64.DEFAULT)
                val bitmap = BitmapFactory.decodeByteArray(imageBytes, 0, imageBytes.size)
                imgProfile.setImageBitmap(bitmap)
            } catch (e: Exception) {
                e.printStackTrace()
                Toast.makeText(this, "Failed to load profile photo", Toast.LENGTH_SHORT).show()
            }
        }

        // Edit button click
        btnEdit.setOnClickListener {
            startActivity(Intent(this, EditProfileActivity::class.java))
        }
    }
}
