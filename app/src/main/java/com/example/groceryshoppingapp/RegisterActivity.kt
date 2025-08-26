package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.os.CountDownTimer
import android.view.View
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.utils.SessionManager
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory

class RegisterActivity : AppCompatActivity() {

    private lateinit var etName: EditText
    private lateinit var etEmail: EditText
    private lateinit var etPhone: EditText
    private lateinit var spinnerRole: Spinner
    private lateinit var etOtp: EditText
    private lateinit var btnSendOtp: Button
    private lateinit var btnVerifyOtp: Button
    private lateinit var btnResendOtp: Button
    private lateinit var tvTimer: TextView

    private var otpSent = false
    private var resendAttempts = 0
    private var countdownTimer: CountDownTimer? = null
    private lateinit var api: ApiService


    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_register_otp)

        etName = findViewById(R.id.et_name)
        etEmail = findViewById(R.id.et_email)
        etPhone = findViewById(R.id.et_phone)
        spinnerRole = findViewById(R.id.spinner_role)
        etOtp = findViewById(R.id.et_otp)
        btnSendOtp = findViewById(R.id.btn_send_otp)
        btnVerifyOtp = findViewById(R.id.btn_verify_otp)
        btnResendOtp = findViewById(R.id.btn_resend_otp)
        tvTimer = findViewById(R.id.tv_timer)

        // Spinner for role selection
        ArrayAdapter.createFromResource(
            this,
            R.array.roles_array, // ["Customer", "ShopOwner"]
            android.R.layout.simple_spinner_item
        ).also { adapter ->
            adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
            spinnerRole.adapter = adapter
        }

        // Retrofit setup
        val retrofit = Retrofit.Builder()
            .baseUrl("https://grocery-shopping-app-yyqx.onrender.com/")
            .addConverterFactory(GsonConverterFactory.create())
            .build()

        api = retrofit.create(ApiService::class.java)

        btnSendOtp.setOnClickListener { sendOtp() }
        btnVerifyOtp.setOnClickListener { verifyOtp() }
        btnResendOtp.setOnClickListener { resendOtp() }
    }

    private fun sendOtp() {
        val email = etEmail.text.toString().trim()
        val name = etName.text.toString().trim()
        val phone = etPhone.text.toString().trim()

        if (email.isEmpty() || name.isEmpty() || phone.isEmpty()) {
            Toast.makeText(this, "Fill all fields", Toast.LENGTH_SHORT).show()
            return
        }

        val body = mapOf("email" to email)
        api.sendOtp(body).enqueue(object : Callback<Map<String, String>> {
            override fun onResponse(call: Call<Map<String, String>>, response: Response<Map<String, String>>) {
                if (response.isSuccessful) {
                    Toast.makeText(this@RegisterActivity, "OTP sent!", Toast.LENGTH_SHORT).show()
                    otpSent = true
                    showOtpFields()
                    startTimer()
                } else {
                    Toast.makeText(this@RegisterActivity, "Failed to send OTP", Toast.LENGTH_SHORT).show()
                }
            }

            override fun onFailure(call: Call<Map<String, String>>, t: Throwable) {
                Toast.makeText(this@RegisterActivity, "Error: ${t.message}", Toast.LENGTH_SHORT).show()
            }
        })
    }

    private fun showOtpFields() {
        etOtp.visibility = View.VISIBLE
        btnVerifyOtp.visibility = View.VISIBLE
        tvTimer.visibility = View.VISIBLE
        btnResendOtp.visibility = View.VISIBLE
    }

    private fun startTimer() {
        countdownTimer?.cancel()
        countdownTimer = object : CountDownTimer(120000, 1000) {
            override fun onTick(millisUntilFinished: Long) {
                val minutes = (millisUntilFinished / 1000) / 60
                val seconds = (millisUntilFinished / 1000) % 60
                tvTimer.text = String.format("%02d:%02d", minutes, seconds)
            }
            override fun onFinish() {
                Toast.makeText(this@RegisterActivity, "OTP expired. Please resend.", Toast.LENGTH_SHORT).show()
                btnVerifyOtp.isEnabled = false
            }
        }.start()
        btnVerifyOtp.isEnabled = true
    }

    private fun verifyOtp() {
        if (!otpSent) return
        val email = etEmail.text.toString().trim()
        val otp = etOtp.text.toString().trim()
        val name = etName.text.toString().trim()
        val phone = etPhone.text.toString().trim()
        val role = spinnerRole.selectedItem.toString().lowercase()

        if (otp.isEmpty()) {
            Toast.makeText(this, "Enter OTP", Toast.LENGTH_SHORT).show()
            return
        }

        val body = mapOf("email" to email, "otp" to otp)
        api.verifyOtp(body).enqueue(object : Callback<Map<String, String>> {
            override fun onResponse(call: Call<Map<String, String>>, response: Response<Map<String, String>>) {
                if (response.isSuccessful && response.body()?.get("status") == "success") {
                    // OTP verified → register user in backend (Firebase handled there)
                    registerUserBackend(name, email, phone, role)
                } else {
                    Toast.makeText(this@RegisterActivity, "Invalid OTP", Toast.LENGTH_SHORT).show()
                }
            }

            override fun onFailure(call: Call<Map<String, String>>, t: Throwable) {
                Toast.makeText(this@RegisterActivity, "Error: ${t.message}", Toast.LENGTH_SHORT).show()
            }
        })
    }

    private fun registerUserBackend(name: String, email: String, phone: String, role: String) {
        val body = mapOf(
            "name" to name,
            "email" to email,
            "phone" to phone,
            "role" to role
        )

        api.registerAfterOtp(body).enqueue(object : Callback<Map<String, String>> {
            override fun onResponse(call: Call<Map<String, String>>, response: Response<Map<String, String>>) {
                if (response.isSuccessful && response.body()?.get("success") == "true") {
                    Toast.makeText(this@RegisterActivity, "✅ Registered successfully!", Toast.LENGTH_SHORT).show()

                    // Save basic profile locally
                    SessionManager.saveUserProfile(this@RegisterActivity, name, "", phone, email, "", "")

                    // Redirect based on role
                    if (role == "shopowner") {
                        val shop = response.body()?.get("shop") // optional
                        val intent = Intent(this@RegisterActivity, CreateShopActivity::class.java)
                        startActivity(intent)
                    } else {
                        val intent = Intent(this@RegisterActivity, CustomerHomeActivity::class.java)
                        startActivity(intent)
                    }
                    finish()
                } else {
                    Toast.makeText(this@RegisterActivity, "Registration failed", Toast.LENGTH_SHORT).show()
                }
            }

            override fun onFailure(call: Call<Map<String, String>>, t: Throwable) {
                Toast.makeText(this@RegisterActivity, "Error: ${t.message}", Toast.LENGTH_SHORT).show()
            }
        })
    }

    private fun resendOtp() {
        if (resendAttempts >= 3) {
            Toast.makeText(this, "Maximum resend attempts reached", Toast.LENGTH_SHORT).show()
            return
        }
        resendAttempts++
        sendOtp()
        Toast.makeText(this, "Resending OTP ($resendAttempts/3)", Toast.LENGTH_SHORT).show()
    }
}
