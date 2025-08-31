package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.os.CountDownTimer
import android.view.View
import android.view.animation.AnimationUtils
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
    private lateinit var etUsername: EditText

    private lateinit var etPassword: EditText
    private lateinit var etConfirmPassword: EditText
    private lateinit var ivPasswordCheck: ImageView

    private lateinit var otpFields: List<EditText>

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
        etUsername = findViewById(R.id.et_username)
        spinnerRole = findViewById(R.id.spinner_role)

        etPassword = findViewById(R.id.et_password)
        etConfirmPassword = findViewById(R.id.et_confirm_password)
        ivPasswordCheck = findViewById(R.id.iv_password_check)

        otpFields = listOf(
            findViewById(R.id.otp_1),
            findViewById(R.id.otp_2),
            findViewById(R.id.otp_3),
            findViewById(R.id.otp_4),
            findViewById(R.id.otp_5),
            findViewById(R.id.otp_6)
        )

        btnSendOtp = findViewById(R.id.btn_send_otp)
        btnVerifyOtp = findViewById(R.id.btn_verify_otp)
        btnResendOtp = findViewById(R.id.btn_resend_otp)
        tvTimer = findViewById(R.id.tv_timer)

        ArrayAdapter.createFromResource(
            this,
            R.array.roles_array,
            android.R.layout.simple_spinner_item
        ).also { adapter ->
            adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
            spinnerRole.adapter = adapter
        }

        val retrofit = Retrofit.Builder()
            .baseUrl("https://grocery-shopping-app-yyqx.onrender.com/")
            .addConverterFactory(GsonConverterFactory.create())
            .build()

        api = retrofit.create(ApiService::class.java)

        btnSendOtp.setOnClickListener { sendOtp() }
        btnVerifyOtp.setOnClickListener { verifyOtp() }
        btnResendOtp.setOnClickListener { resendOtp() }

        setupPasswordValidation()
        setupOtpBoxes()
    }

    private fun setupPasswordValidation() {
        btnVerifyOtp.isEnabled = false
        val watcher = object : android.text.TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
                validatePasswords()
            }
            override fun afterTextChanged(s: android.text.Editable?) {}
        }
        etPassword.addTextChangedListener(watcher)
        etConfirmPassword.addTextChangedListener(watcher)
    }

    private fun validatePasswords() {
        val password = etPassword.text.toString().trim()
        val confirmPassword = etConfirmPassword.text.toString().trim()

        if (password.isNotEmpty() && confirmPassword.isNotEmpty()) {
            ivPasswordCheck.visibility = View.VISIBLE
            if (password == confirmPassword) {
                btnVerifyOtp.isEnabled = true
                ivPasswordCheck.setImageResource(R.drawable.ic_check_green)
                etConfirmPassword.error = null
            } else {
                btnVerifyOtp.isEnabled = false
                ivPasswordCheck.setImageResource(R.drawable.ic_close_red)
                etConfirmPassword.error = "Passwords do not match"
                val shake = AnimationUtils.loadAnimation(this, R.anim.shake)
                etConfirmPassword.startAnimation(shake)
            }
        } else {
            btnVerifyOtp.isEnabled = false
            ivPasswordCheck.visibility = View.GONE
        }
    }

    private fun setupOtpBoxes() {
        for (i in otpFields.indices) {
            otpFields[i].addTextChangedListener(object : android.text.TextWatcher {
                override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
                override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
                    if (s?.length == 1 && i < otpFields.size - 1) otpFields[i + 1].requestFocus()
                    else if (s?.isEmpty() == true && i > 0) otpFields[i - 1].requestFocus()
                    validateOtpBoxes()
                }
                override fun afterTextChanged(s: android.text.Editable?) {}
            })
        }
    }

    private fun getOtpFromBoxes(): String {
        val sb = StringBuilder()
        otpFields.forEach { sb.append(it.text.toString().trim()) }
        return sb.toString()
    }

    private fun validateOtpBoxes() {
        btnVerifyOtp.isEnabled = getOtpFromBoxes().length == 6
    }

    private fun sendOtp() {
        val email = etEmail.text.toString().trim()
        val name = etName.text.toString().trim()
        val phone = etPhone.text.toString().trim()
        val username = etUsername.text.toString().trim()
        val password = etPassword.text.toString().trim()
        val confirmPassword = etConfirmPassword.text.toString().trim()

        if (username.isEmpty() || email.isEmpty() || name.isEmpty() || phone.isEmpty() ||
            password.isEmpty() || confirmPassword.isEmpty()
        ) {
            Toast.makeText(this, "Fill all fields", Toast.LENGTH_SHORT).show()
            return
        }

        if (password != confirmPassword) {
            Toast.makeText(this, "Passwords do not match", Toast.LENGTH_SHORT).show()
            return
        }

        api.sendOtp(mapOf("email" to email))
            .enqueue(object : Callback<Map<String, String>> {
                override fun onResponse(
                    call: Call<Map<String, String>>,
                    response: Response<Map<String, String>>
                ) {
                    if (response.isSuccessful) {
                        Toast.makeText(this@RegisterActivity, "OTP sent!", Toast.LENGTH_SHORT).show()
                        otpSent = true
                        showOtpFields()
                        startTimer()
                    } else Toast.makeText(this@RegisterActivity, "Failed to send OTP", Toast.LENGTH_SHORT).show()
                }

                override fun onFailure(call: Call<Map<String, String>>, t: Throwable) {
                    Toast.makeText(this@RegisterActivity, "Error: ${t.message}", Toast.LENGTH_SHORT).show()
                }
            })
    }

    private fun showOtpFields() {
        findViewById<LinearLayout>(R.id.layout_otp_boxes).visibility = View.VISIBLE
        btnVerifyOtp.visibility = View.VISIBLE
        tvTimer.visibility = View.VISIBLE
        btnResendOtp.visibility = View.VISIBLE
        otpFields[0].requestFocus()
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
        btnVerifyOtp.isEnabled = false
    }

    private fun verifyOtp() {
        if (!otpSent) return
        val email = etEmail.text.toString().trim()
        val otp = getOtpFromBoxes()
        val name = etName.text.toString().trim()
        val phone = etPhone.text.toString().trim()
        val username = etUsername.text.toString().trim()
        val role = spinnerRole.selectedItem.toString().lowercase()
        val password = etPassword.text.toString().trim()

        if (otp.length != 6) {
            Toast.makeText(this, "Enter a valid 6-digit OTP", Toast.LENGTH_SHORT).show()
            return
        }

        api.verifyOtp(mapOf("email" to email, "otp" to otp))
            .enqueue(object : Callback<Map<String, String>> {
                override fun onResponse(
                    call: Call<Map<String, String>>,
                    response: Response<Map<String, String>>
                ) {
                    if (response.isSuccessful && response.body()?.get("status") == "success") {
                        registerUserBackend(name, username, email, phone, role, password)
                    } else {
                        Toast.makeText(this@RegisterActivity, "Invalid OTP", Toast.LENGTH_SHORT).show()
                    }
                }

                override fun onFailure(call: Call<Map<String, String>>, t: Throwable) {
                    Toast.makeText(this@RegisterActivity, "Error: ${t.message}", Toast.LENGTH_SHORT).show()
                }
            })
    }

    private fun registerUserBackend(
        name: String,
        username: String,
        email: String,
        phone: String,
        role: String,
        password: String
    ) {
        val body = mapOf(
            "full_name" to name,
            "username" to username,
            "email" to email,
            "phone" to phone,
            "role" to role,
            "password" to password
        )

        api.registerAfterOtp(body)
            .enqueue(object : Callback<Map<String, Any>> {
                override fun onResponse(
                    call: Call<Map<String, Any>>,
                    response: Response<Map<String, Any>>
                ) {
                    if (response.isSuccessful) {
                        val resBody = response.body()
                        val success = resBody?.get("success") as? Boolean ?: false

                        if (success) {
                            val user = resBody?.get("user") as? Map<*, *>
                            val shop = resBody?.get("shop") as? Map<*, *>

                            val savedRole = user?.get("role") as? String ?: role
                            val usernameSaved = user?.get("username") as? String ?: username

                            SessionManager.saveLogin(this@RegisterActivity, usernameSaved, savedRole)

                            if (savedRole == "shopowner") {
                                val shopkeeperId = user?.get("shopkeeper_id") as? String ?: ""
                                SessionManager.setShopkeeperId(this@RegisterActivity, shopkeeperId)

                                shop?.let {
                                    val shopId = it["shop_id"] as? String ?: ""
                                    val shopName = it["name"] as? String ?: ""
                                    SessionManager.setShopInfo(this@RegisterActivity, shopId, shopName)
                                }

                                startActivity(Intent(this@RegisterActivity, CreateShopActivity::class.java))
                            } else {
                                val customerId = user?.get("customer_id") as? String ?: ""
                                SessionManager.setCustomerId(this@RegisterActivity, customerId)
                                startActivity(Intent(this@RegisterActivity, CustomerHomeActivity::class.java))
                            }

                            finish()
                        } else {
                            val msg = resBody?.get("message") as? String ?: "Registration failed"
                            Toast.makeText(this@RegisterActivity, msg, Toast.LENGTH_SHORT).show()
                        }
                    } else {
                        Toast.makeText(this@RegisterActivity, "Registration failed: ${response.code()}", Toast.LENGTH_SHORT).show()
                    }
                }

                override fun onFailure(call: Call<Map<String, Any>>, t: Throwable) {
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
